// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd.
 * @file h102_profile_control.c
 * @brief Provide asynchronous preset-selection IIO attributes and exclusive root-service IPC.
 * @details One request, sequence checking and a 30-second lease prevent false completion.
 * @author LogicRF Technologies
 * @architect LogicRF
 * @email info@logicrf.com
 * @website https://www.logicrf.com
 * @version 1.0.0
 * @date 2026-10-08
 * @note A mutex protects caches; an open service FD holds the module reference.
 */
#include <linux/capability.h>
#include <linux/fs.h>
#include <linux/iio/iio.h>
#include <linux/iio/sysfs.h>
#include <linux/jiffies.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include "h102_profile_control.h"

/* Five-second heartbeat and 30-second lease; no timer changes hardware configuration. */
#define LEASE (30 * HZ)
struct h102_control {
 struct mutex lock;
 wait_queue_head_t wait;
 bool connected, pending, delivered;
 unsigned long heartbeat;
 u64 ticket;
 struct h102_request request;
 struct h102_update cache;
};
static struct h102_control control;
static struct platform_device *parent;
static struct iio_dev *device;
static const char *const phases[] = {
 "unavailable", "ready", "applying", "applied", "rolled_back", "rejected", "queued"
};
enum h102_attr { AVAILABLE, SELECT, ACTIVE, PREVIOUS, STATUS, ERROR,
 CONFIGURATION_ID, REQUEST_ID, ACTIVE_INFO, ABI_VERSION };

/* Restrict preset IDs to lowercase ASCII to prevent path or command injection. */
static bool valid_id(const char *id)
{
 size_t i, n = strnlen(id, H102_CONTROL_ID);
 if (!n || n == H102_CONTROL_ID)
  return false;
 for (i = 0; i < n; i++)
  if (!((id[i] >= 'a' && id[i] <= 'z') ||
        (id[i] >= '0' && id[i] <= '9') || (i && id[i] == '-')))
   return false;
 return true;
}
/* Match complete words in a space-separated catalog. */
static bool listed(const char *list, const char *id)
{
 const char *p = list;
 size_t n = strlen(id), len;
 while (*p) {
  len = strcspn(p, " ");
  if (len == n && !strncmp(p, id, n))
   return true;
  p += len;
  if (*p)
   p++;
 }
 return false;
}
/* Validate the service catalog, terminators and phase before accepting data. */
static bool valid_update(const struct h102_update *u)
{
 const char *p;
 char id[H102_CONTROL_ID];
 size_t n;
 if (le32_to_cpu(u->version) != H102_CONTROL_ABI || u->reserved ||
     le32_to_cpu(u->phase) > H102_REJECTED ||
     !memchr(u->active, 0, sizeof(u->active)) ||
     !memchr(u->previous, 0, sizeof(u->previous)) ||
     !memchr(u->error, 0, sizeof(u->error)) ||
     !memchr(u->info, 0, sizeof(u->info)) ||
     !memchr(u->available, 0, sizeof(u->available)))
  return false;
 p = u->available;
 while (*p) {
  n = strcspn(p, " ");
  if (!n || n >= sizeof(id))
   return false;
  memcpy(id, p, n);
  id[n] = 0;
  if (!valid_id(id))
   return false;
  p += n;
  if (*p && !*++p)
   return false;
 }
 if (*u->active && (!valid_id(u->active) || !listed(u->available, u->active)))
  return false;
 if (*u->previous && (!valid_id(u->previous) || !listed(u->available, u->previous)))
  return false;
 if (le32_to_cpu(u->phase) != H102_UNAVAILABLE &&
     (!*u->active || !le32_to_cpu(u->configuration_id)))
  return false;
 return true;
}
/* Caller holds lock; expiry hides status but does not cancel independent recovery. */
static bool online(void)
{
 return control.connected && time_before(jiffies, control.heartbeat + LEASE);
}
static ssize_t attr_show(struct device *dev, struct device_attribute *attr, char *buf)
{
 struct iio_dev_attr *a = to_iio_dev_attr(attr);
 u32 phase;
 ssize_t ret;
 mutex_lock(&control.lock);
 phase = online() ? le32_to_cpu(control.cache.phase) : H102_UNAVAILABLE;
 switch (a->address) {
 case AVAILABLE: ret = sysfs_emit(buf, "%s\n", online() ? control.cache.available : ""); break;
 case SELECT: ret = sysfs_emit(buf, "%s\n", control.request.id); break;
 case STATUS: ret = sysfs_emit(buf, "%s\n", phases[phase]); break;
 case ERROR: ret = sysfs_emit(buf, "%s\n", online() ? control.cache.error : "BACKEND_UNAVAILABLE"); break;
 case REQUEST_ID: ret = sysfs_emit(buf, "%llu\n", control.ticket); break;
 case ABI_VERSION: ret = sysfs_emit(buf, "%u\n", H102_CONTROL_ABI); break;
 default:
  if (phase == H102_UNAVAILABLE || phase == H102_QUEUED || phase == H102_APPLYING) {
   ret = -ENODATA;
   break;
  }
  switch (a->address) {
  case ACTIVE: ret = sysfs_emit(buf, "%s\n", control.cache.active); break;
  case PREVIOUS: ret = sysfs_emit(buf, "%s\n", *control.cache.previous ? control.cache.previous : "-"); break;
  case CONFIGURATION_ID: ret = sysfs_emit(buf, "%u\n", le32_to_cpu(control.cache.configuration_id)); break;
  case ACTIVE_INFO: ret = sysfs_emit(buf, "%s\n", control.cache.info); break;
  default: ret = -EINVAL;
  }
 }
 mutex_unlock(&control.lock);
 return ret;
}
/* A successful sysfs/libiio write queues a request; configuration is not yet complete. */
static ssize_t select_store(struct device *dev, struct device_attribute *attr,
       const char *buf, size_t count)
{
 char id[H102_CONTROL_ID];
 size_t n = count;
 ssize_t ret = count;
 /* libiio attr_write includes a trailing NUL; reject embedded NULs. */
 if (n && buf[n - 1] == '\0')
  n--;
 if (n && buf[n - 1] == '\n')
  n--;
 if (!n || n >= sizeof(id) || memchr(buf, 0, n))
  return -EINVAL;
 memcpy(id, buf, n);
 id[n] = 0;
 if (!valid_id(id))
  return -EINVAL;
 mutex_lock(&control.lock);
 if (!online() || le32_to_cpu(control.cache.phase) == H102_UNAVAILABLE)
  ret = -ENOTCONN;
 else if (control.pending)
  ret = -EBUSY;
 else if (!listed(control.cache.available, id))
  ret = -EINVAL;
 else if (control.ticket == U64_MAX)
  ret = -EOVERFLOW;
 else {
  control.ticket++;
  memset(&control.request, 0, sizeof(control.request));
  control.request.version = cpu_to_le32(H102_CONTROL_ABI);
  control.request.ticket = cpu_to_le64(control.ticket);
  strscpy(control.request.id, id, sizeof(control.request.id));
  control.pending = true;
  control.delivered = false;
  control.cache.phase = cpu_to_le32(H102_QUEUED);
  control.cache.error[0] = 0;
  wake_up_interruptible(&control.wait);
 }
 mutex_unlock(&control.lock);
 return ret;
}
#define RO(name, addr) static IIO_DEVICE_ATTR(name, 0444, attr_show, NULL, addr)
RO(available, AVAILABLE); RO(active, ACTIVE); RO(previous, PREVIOUS);
RO(status, STATUS); RO(error, ERROR); RO(configuration_id, CONFIGURATION_ID);
RO(request_id, REQUEST_ID); RO(active_info, ACTIVE_INFO); RO(abi_version, ABI_VERSION);
static IIO_DEVICE_ATTR(select, 0644, attr_show, select_store, SELECT);
static struct attribute *attrs[] = {
 &iio_dev_attr_available.dev_attr.attr, &iio_dev_attr_select.dev_attr.attr,
 &iio_dev_attr_active.dev_attr.attr, &iio_dev_attr_previous.dev_attr.attr,
 &iio_dev_attr_status.dev_attr.attr, &iio_dev_attr_error.dev_attr.attr,
 &iio_dev_attr_configuration_id.dev_attr.attr, &iio_dev_attr_request_id.dev_attr.attr,
 &iio_dev_attr_active_info.dev_attr.attr, &iio_dev_attr_abi_version.dev_attr.attr, NULL
};
static const struct attribute_group group = { .attrs = attrs };
static const struct iio_info info = { .attrs = &group };

/* Exclusive root backend; reconnect must publish independently verified state first. */
static int backend_open(struct inode *inode, struct file *file)
{
 int ret = 0;
 if (!capable(CAP_SYS_ADMIN))
  return -EPERM;
 mutex_lock(&control.lock);
 if (control.connected)
  ret = -EBUSY;
 else {
  control.connected = true;
  control.pending = false;
  control.delivered = false;
  memset(&control.cache, 0, sizeof(control.cache));
  control.heartbeat = jiffies;
 }
 mutex_unlock(&control.lock);
 return ret;
}
static int backend_release(struct inode *inode, struct file *file)
{
 mutex_lock(&control.lock);
 control.connected = false;
 control.pending = false;
 control.delivered = false;
 control.cache.phase = 0;
 mutex_unlock(&control.lock);
 return 0;
}
static ssize_t backend_read(struct file *file, char __user *buf, size_t len, loff_t *pos)
{
 ssize_t ret = sizeof(control.request);
 if (len != sizeof(control.request))
  return -EINVAL;
 mutex_lock(&control.lock);
 if (!control.pending || control.delivered)
  ret = -EAGAIN;
 else if (copy_to_user(buf, &control.request, sizeof(control.request)))
  ret = -EFAULT;
 else {
  control.delivered = true;
  control.cache.phase = cpu_to_le32(H102_APPLYING);
 }
 mutex_unlock(&control.lock);
 return ret;
}
/* Completion must match an issued request; idle heartbeat cannot overwrite queued work. */
static ssize_t backend_write(struct file *file, const char __user *buf, size_t len, loff_t *pos)
{
 struct h102_update *u;
 u64 ticket;
 u32 phase;
 ssize_t ret = len;
 if (len != sizeof(*u))
  return -EINVAL;
 u = memdup_user(buf, len);
 if (IS_ERR(u))
  return PTR_ERR(u);
 if (!valid_update(u)) {
  ret = -EINVAL;
  goto out;
 }
 ticket = le64_to_cpu(u->ticket);
 phase = le32_to_cpu(u->phase);
 mutex_lock(&control.lock);
 if (ticket != control.ticket ||
     (control.pending && (!control.delivered || phase == H102_READY)) ||
     (!control.pending && phase == H102_APPLYING))
  ret = -ESTALE;
 else {
  memcpy(&control.cache, u, sizeof(*u));
  control.heartbeat = jiffies;
  if (phase != H102_APPLYING)
   control.pending = false;
 }
 mutex_unlock(&control.lock);
 out:
 kfree(u);
 return ret;
}
static __poll_t backend_poll(struct file *file, poll_table *wait)
{
 __poll_t mask = 0;
 poll_wait(file, &control.wait, wait);
 mutex_lock(&control.lock);
 if (control.pending && !control.delivered)
  mask = EPOLLIN | EPOLLRDNORM;
 mutex_unlock(&control.lock);
 return mask;
}
static const struct file_operations operations = {
 .owner = THIS_MODULE, .open = backend_open, .release = backend_release,
 .read = backend_read, .write = backend_write, .poll = backend_poll, .llseek = no_llseek,
};
static struct miscdevice backend = {
 .minor = MISC_DYNAMIC_MINOR, .name = "h102-profile-control", .fops = &operations, .mode = 0600,
};
static int __init control_init(void)
{
 int ret;
 static_assert(sizeof(struct h102_request) == 80);
 static_assert(sizeof(struct h102_update) == 4504);
 mutex_init(&control.lock);
 init_waitqueue_head(&control.wait);
 parent = platform_device_register_simple("h102-profile-control", -1, NULL, 0);
 if (IS_ERR(parent))
  return PTR_ERR(parent);
 device = iio_device_alloc(&parent->dev, 0);
 if (!device) {
  ret = -ENOMEM;
  goto unregister_parent;
 }
 device->name = "h102-profile-control";
 device->modes = INDIO_DIRECT_MODE;
 device->info = &info;
 ret = iio_device_register(device);
 if (ret)
  goto free_device;
 ret = misc_register(&backend);
 if (!ret)
  return 0;
 iio_device_unregister(device);
 free_device:
 iio_device_free(device);
 unregister_parent:
 platform_device_unregister(parent);
 return ret;
}
static void __exit control_exit(void)
{
 misc_deregister(&backend);
 iio_device_unregister(device);
 iio_device_free(device);
 platform_device_unregister(parent);
}
module_init(control_init);
module_exit(control_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("LogicRF Technologies");
MODULE_DESCRIPTION("H102 asynchronous software IIO preset selection");
