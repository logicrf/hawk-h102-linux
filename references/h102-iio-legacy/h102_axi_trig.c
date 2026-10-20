#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/io.h>
#include <linux/iio/iio.h>
#include <linux/iio/sysfs.h>
#include <linux/iio/types.h>
#include <linux/iio/driver.h>

#define DEVICE_NAME "h102_axi_trig"

// Register offsets
enum h102_axi_trig_registers {
    REG_HW_VER = 0x00,
    REG_RTL_VER = 0x04,
    REG_RSV_VER = 0x08,
    //0x03
    REG_VIO_DEBUG_EN = 0x0C,

    //0x10~0x12
    REG_PPS_SEL = 0x40,
    REG_CH0_TRIG_SEL = 0x44,
    REG_CH1_TRIG_SEL = 0x48,

    //CH0-0x20~0x28
    REG_CH0_TRIG_PULSE = 0x80,
    REG_CH0_TRIG_LENGTH = 0x84,
    REG_CH0_TRIG_EN = 0x88,
    REG_CH0_PACK_MODE_SEL = 0x8C,
    REG_CH0_CPACK_ALWAYS_ON = 0x90,
    REG_CH0_FRAME_FIXHEAD = 0x94,
    REG_CH0_FRAME_FIXHEAD_VAL = 0x98,
    REG_CH0_CHDR_DATA = 0x9C,
    REG_CH0_CHDR_VAL = 0xA0,
    //CH1-0x30~0x38
    REG_CH1_TRIG_PULSE = 0xC0,
    REG_CH1_TRIG_LENGTH = 0xC4,
    REG_CH1_TRIG_EN = 0xC8,
    REG_CH1_PACK_MODE_SEL = 0xCC,
    REG_CH1_CPACK_ALWAYS_ON = 0xD0,
    REG_CH1_FRAME_FIXHEAD = 0xD4,
    REG_CH1_FRAME_FIXHEAD_VAL = 0xD8,
    REG_CH1_CHDR_DATA = 0xDC,
    REG_CH1_CHDR_VAL = 0xE0,
};

struct h102_state {
    void __iomem *regs;
    struct mutex		lock;
};


void h102_axi_trig_write(struct h102_state *st,unsigned int reg, unsigned int val)
{
	iowrite32(val, st->regs + reg);
}


int h102_axi_trig_read(struct h102_state *st, unsigned int reg)
{
	return ioread32(st->regs + reg);
}


// Read register value
static ssize_t h102_axi_trig_show(struct device *dev,
                                 struct device_attribute *attr,
                                 char *buf)
{
    struct iio_dev *indio_dev = dev_to_iio_dev(dev);
    //struct iio_dev_attr *this_attr = to_iio_dev_attr(attr);
    struct h102_state *st = iio_priv(indio_dev);
    ssize_t len = 0;
    u32 val;

    if (strcmp(attr->attr.name, "hw_ver") == 0)
        val = ioread32(st->regs + REG_HW_VER);
    else if (strcmp(attr->attr.name, "rtl_ver") == 0)
        val = ioread32(st->regs + REG_RTL_VER);
    else if (strcmp(attr->attr.name, "rsv_ver") == 0)
        val = ioread32(st->regs + REG_RSV_VER);
    else if (strcmp(attr->attr.name, "vio_debug_en") == 0)
        val = ioread32(st->regs + REG_VIO_DEBUG_EN);
    else if (strcmp(attr->attr.name, "pps_sel") == 0)
        val = ioread32(st->regs + REG_PPS_SEL);
    else if (strcmp(attr->attr.name, "ch0_trig_sel") == 0)
        val = ioread32(st->regs + REG_CH0_TRIG_SEL);     
    else if (strcmp(attr->attr.name, "ch1_trig_sel") == 0)
        val = ioread32(st->regs + REG_CH1_TRIG_SEL);   
    else if (strcmp(attr->attr.name, "ch0_trig_pulse") == 0)
        val = ioread32(st->regs + REG_CH0_TRIG_PULSE);
    else if (strcmp(attr->attr.name, "ch0_trig_length") == 0)
        val = ioread32(st->regs + REG_CH0_TRIG_LENGTH);
    else if (strcmp(attr->attr.name, "ch0_trig_en") == 0)
        val = ioread32(st->regs + REG_CH0_TRIG_EN);
    else if (strcmp(attr->attr.name, "ch0_pack_mode_sel") == 0)
        val = ioread32(st->regs + REG_CH0_PACK_MODE_SEL);
    else if (strcmp(attr->attr.name, "ch0_cpack_always_on") == 0)
        val = ioread32(st->regs + REG_CH0_CPACK_ALWAYS_ON);
    else if (strcmp(attr->attr.name, "ch0_frame_fixhead") == 0)
        val = ioread32(st->regs + REG_CH0_FRAME_FIXHEAD);
    else if (strcmp(attr->attr.name, "ch0_frame_fixhead_val") == 0)
        val = ioread32(st->regs + REG_CH0_FRAME_FIXHEAD_VAL);
    else if (strcmp(attr->attr.name, "ch0_chdr_data") == 0)
        val = ioread32(st->regs + REG_CH0_CHDR_DATA);
    else if (strcmp(attr->attr.name, "ch0_chdr_val") == 0)
        val = ioread32(st->regs + REG_CH0_CHDR_VAL);
    else if (strcmp(attr->attr.name, "ch1_trig_pulse") == 0)
        val = ioread32(st->regs + REG_CH1_TRIG_PULSE);
    else if (strcmp(attr->attr.name, "ch1_trig_length") == 0)
        val = ioread32(st->regs + REG_CH1_TRIG_LENGTH);
    else if (strcmp(attr->attr.name, "ch1_trig_en") == 0)
        val = ioread32(st->regs + REG_CH1_TRIG_EN);
    else if (strcmp(attr->attr.name, "ch1_pack_mode_sel") == 0)
        val = ioread32(st->regs + REG_CH1_PACK_MODE_SEL);
    else if (strcmp(attr->attr.name, "ch1_cpack_always_on") == 0)
        val = ioread32(st->regs + REG_CH1_CPACK_ALWAYS_ON);
    else if (strcmp(attr->attr.name, "ch1_frame_fixhead") == 0)
        val = ioread32(st->regs + REG_CH1_FRAME_FIXHEAD);
    else if (strcmp(attr->attr.name, "ch1_frame_fixhead_val") == 0)
        val = ioread32(st->regs + REG_CH1_FRAME_FIXHEAD_VAL);
    else if (strcmp(attr->attr.name, "ch1_chdr_data") == 0)
        val = ioread32(st->regs + REG_CH1_CHDR_DATA);
    else if (strcmp(attr->attr.name, "ch1_chdr_val") == 0)
        val = ioread32(st->regs + REG_CH1_CHDR_VAL);
    else
        return -EINVAL;

    return len;
}

// Write register value
static ssize_t h102_axi_trig_store(struct device *dev,
                                  struct device_attribute *attr,
                                  const char *buf,
                                  size_t count)
{
    struct iio_dev *indio_dev = dev_to_iio_dev(dev);
    struct h102_state *st = iio_priv(indio_dev);
    unsigned long val;
    int ret;

    ret = kstrtoul(buf, 0, &val);
    if (ret)
        return ret;

    if (strcmp(attr->attr.name, "vio_debug_en") == 0)
        iowrite32(val, st->regs + REG_VIO_DEBUG_EN);
    else if (strcmp(attr->attr.name, "pps_sel") == 0)
        iowrite32(val, st->regs + REG_PPS_SEL);
    else if (strcmp(attr->attr.name, "ch0_trig_sel") == 0)
        iowrite32(val, st->regs + REG_CH0_TRIG_SEL);     
    else if (strcmp(attr->attr.name, "ch1_trig_sel") == 0)
        iowrite32(val, st->regs + REG_CH1_TRIG_SEL);   
    else if (strcmp(attr->attr.name, "ch0_trig_pulse") == 0)
        iowrite32(val, st->regs + REG_CH0_TRIG_PULSE);
    else if (strcmp(attr->attr.name, "ch0_trig_length") == 0)
        iowrite32(val, st->regs + REG_CH0_TRIG_LENGTH);
    else if (strcmp(attr->attr.name, "ch0_trig_en") == 0)
        iowrite32(val, st->regs + REG_CH0_TRIG_EN);
    else if (strcmp(attr->attr.name, "ch0_pack_mode_sel") == 0)
        iowrite32(val, st->regs + REG_CH0_PACK_MODE_SEL);
    else if (strcmp(attr->attr.name, "ch0_cpack_always_on") == 0)
        iowrite32(val, st->regs + REG_CH0_CPACK_ALWAYS_ON);
    else if (strcmp(attr->attr.name, "ch0_frame_fixhead") == 0)
        iowrite32(val, st->regs + REG_CH0_FRAME_FIXHEAD);
    else if (strcmp(attr->attr.name, "ch0_frame_fixhead_val") == 0)
        iowrite32(val, st->regs + REG_CH0_FRAME_FIXHEAD_VAL);
    else if (strcmp(attr->attr.name, "ch0_chdr_data") == 0)
        iowrite32(val, st->regs + REG_CH0_CHDR_DATA);
    else if (strcmp(attr->attr.name, "ch0_chdr_val") == 0)
        iowrite32(val, st->regs + REG_CH0_CHDR_VAL);
    else if (strcmp(attr->attr.name, "ch1_trig_pulse") == 0)
        iowrite32(val, st->regs + REG_CH1_TRIG_PULSE);
    else if (strcmp(attr->attr.name, "ch1_trig_length") == 0)
        iowrite32(val, st->regs + REG_CH1_TRIG_LENGTH);
    else if (strcmp(attr->attr.name, "ch1_trig_en") == 0)
        iowrite32(val, st->regs + REG_CH1_TRIG_EN);
    else if (strcmp(attr->attr.name, "ch1_pack_mode_sel") == 0)
        iowrite32(val, st->regs + REG_CH1_PACK_MODE_SEL);
    else if (strcmp(attr->attr.name, "ch1_cpack_always_on") == 0)
        iowrite32(val, st->regs + REG_CH1_CPACK_ALWAYS_ON);
    else if (strcmp(attr->attr.name, "ch1_frame_fixhead") == 0)
        iowrite32(val, st->regs + REG_CH1_FRAME_FIXHEAD);
    else if (strcmp(attr->attr.name, "ch1_frame_fixhead_val") == 0)
        iowrite32(val, st->regs + REG_CH1_FRAME_FIXHEAD_VAL);
    else if (strcmp(attr->attr.name, "ch1_chdr_data") == 0)
        iowrite32(val, st->regs + REG_CH1_CHDR_DATA);
    else if (strcmp(attr->attr.name, "ch1_chdr_val") == 0)
        iowrite32(val, st->regs + REG_CH1_CHDR_VAL);
    else
        return -EINVAL;

    return count;
}

// IIO attribute definitions
static IIO_DEVICE_ATTR(hw_ver, S_IRUGO, h102_axi_trig_show, NULL, 0);
static IIO_DEVICE_ATTR(rtl_ver, S_IRUGO, h102_axi_trig_show, NULL, 1);
static IIO_DEVICE_ATTR(rsv_ver, S_IRUGO, h102_axi_trig_show, NULL, 2);
static IIO_DEVICE_ATTR(vio_debug_en,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 3);
static IIO_DEVICE_ATTR(pps_sel,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 4);
static IIO_DEVICE_ATTR(ch0_trig_sel,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 5);
static IIO_DEVICE_ATTR(ch1_trig_sel,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 6);

static IIO_DEVICE_ATTR(ch0_trig_pulse,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 7);
static IIO_DEVICE_ATTR(ch0_trig_length,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 8);
static IIO_DEVICE_ATTR(ch0_trig_en,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 9);
static IIO_DEVICE_ATTR(ch0_pack_mode_sel,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 10);
static IIO_DEVICE_ATTR(ch0_cpack_always_on,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 11);
static IIO_DEVICE_ATTR(ch0_frame_fixhead,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 12);
static IIO_DEVICE_ATTR(ch0_frame_fixhead_val,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 13);
static IIO_DEVICE_ATTR(ch0_chdr_data,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 14);
static IIO_DEVICE_ATTR(ch0_chdr_val,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 15);

static IIO_DEVICE_ATTR(ch1_trig_pulse,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 16);
static IIO_DEVICE_ATTR(ch1_trig_length,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 17);
static IIO_DEVICE_ATTR(ch1_trig_en,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 18);
static IIO_DEVICE_ATTR(ch1_pack_mode_sel,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 19);
static IIO_DEVICE_ATTR(ch1_cpack_always_on,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 20);
static IIO_DEVICE_ATTR(ch1_frame_fixhead,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 21);
static IIO_DEVICE_ATTR(ch1_frame_fixhead_val,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 22);
static IIO_DEVICE_ATTR(ch1_chdr_data,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 23);
static IIO_DEVICE_ATTR(ch1_chdr_val,S_IRUGO|S_IWUSR, h102_axi_trig_show, h102_axi_trig_store, 24);

// Register IIO attributes
static struct attribute *h102_axi_trig_attributes[] = {
    &iio_dev_attr_hw_ver.dev_attr.attr,
    &iio_dev_attr_rtl_ver.dev_attr.attr,
    &iio_dev_attr_rsv_ver.dev_attr.attr,
    &iio_dev_attr_vio_debug_en.dev_attr.attr,
    &iio_dev_attr_pps_sel.dev_attr.attr,
    &iio_dev_attr_ch0_trig_sel.dev_attr.attr,
    &iio_dev_attr_ch1_trig_sel.dev_attr.attr,
    &iio_dev_attr_ch0_trig_pulse.dev_attr.attr,
    &iio_dev_attr_ch0_trig_length.dev_attr.attr,
    &iio_dev_attr_ch0_trig_en.dev_attr.attr,
    &iio_dev_attr_ch0_pack_mode_sel.dev_attr.attr,
    &iio_dev_attr_ch0_cpack_always_on.dev_attr.attr,
    &iio_dev_attr_ch0_frame_fixhead.dev_attr.attr,
    &iio_dev_attr_ch0_frame_fixhead_val.dev_attr.attr,
    &iio_dev_attr_ch0_chdr_data.dev_attr.attr,
    &iio_dev_attr_ch0_chdr_val.dev_attr.attr,
    &iio_dev_attr_ch1_trig_pulse.dev_attr.attr,
    &iio_dev_attr_ch1_trig_length.dev_attr.attr,
    &iio_dev_attr_ch1_trig_en.dev_attr.attr,
    &iio_dev_attr_ch1_pack_mode_sel.dev_attr.attr,
    &iio_dev_attr_ch1_cpack_always_on.dev_attr.attr,
    &iio_dev_attr_ch1_frame_fixhead.dev_attr.attr,
    &iio_dev_attr_ch1_frame_fixhead_val.dev_attr.attr,
    &iio_dev_attr_ch1_chdr_data.dev_attr.attr,
    &iio_dev_attr_ch1_chdr_val.dev_attr.attr,
    NULL,
};



static const struct attribute_group h102_axi_trig_attribute_group = {
    .attrs = h102_axi_trig_attributes,
};

static int h102_axi_trig_read_raw(struct iio_dev *indio_dev,
                                 struct iio_chan_spec const *chan,
                                 int *val,
                                 int *val2,
                                 long mask)
{
    struct h102_state *st = iio_priv(indio_dev);
    int reg_offset;

    // Trace register access
    if (!st || !st->regs)
    {
        pr_err("h102_axi_trig_read_raw: Null pointer detected, st=%p, st->reg=%p\n", st, st ? st->regs : NULL);
        return -EINVAL;
    }

    switch (mask) {
    case IIO_CHAN_INFO_RAW:
        reg_offset = chan->address;
        *val = ioread32(st->regs + reg_offset);
        return IIO_VAL_INT;
    default:
        return -EINVAL;
    }  


}

static int h102_axi_trig_write_raw(struct iio_dev *indio_dev,
                                  struct iio_chan_spec const *chan,
                                  int val,
                                  int val2,
                                  long mask)
{
    struct h102_state *st = iio_priv(indio_dev);
    //int reg_offset;


    // Trace register access
    if (!st || !st->regs)
    {
        pr_err("h102_axi_trig_show: Null pointer detected, st=%p, st->reg=%p\n", st, st ? st->regs : NULL);
        return -EINVAL;
    }

    if(chan->output){
        iowrite32(val, st->regs + chan->address);
        return 0; 
    }else{
        return -EINVAL;
    }
    // mutex_lock(&st->lock);

    // switch (mask) {
    // case IIO_CHAN_INFO_RAW:
    //     reg_offset = chan->address;
    //     iowrite32(val, st->regs + reg_offset);
    //     return 0;
    // default:
    //     return -EINVAL;
    // }
    // mutex_unlock(&st->lock);
}


static const struct iio_chan_spec h102_axi_trig_channels[] = {
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 0,
        .address = REG_HW_VER,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 1,
        .address = REG_RTL_VER,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 2,
        .address = REG_RSV_VER,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 3,
        .address = REG_VIO_DEBUG_EN,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 4,
        .address = REG_PPS_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 5,
        .address = REG_CH0_TRIG_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },    

    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 6,
        .address = REG_CH1_TRIG_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },


    // ch0
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 7,
        .address = REG_CH0_TRIG_PULSE,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 8,
        .address = REG_CH0_TRIG_LENGTH,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 9,
        .address = REG_CH0_TRIG_EN,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 10,
        .address = REG_CH0_PACK_MODE_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 11,
        .address = REG_CH0_CPACK_ALWAYS_ON,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 12,
        .address = REG_CH0_FRAME_FIXHEAD,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 13,
        .address = REG_CH0_FRAME_FIXHEAD_VAL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 14,
        .address = REG_CH0_CHDR_DATA,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 15,
        .address = REG_CH0_CHDR_VAL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    // Ch1
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 16,
        .address = REG_CH1_TRIG_PULSE,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 17,
        .address = REG_CH1_TRIG_LENGTH,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 18,
        .address = REG_CH1_TRIG_EN,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 19,
        .address = REG_CH1_PACK_MODE_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 20,
        .address = REG_CH1_CPACK_ALWAYS_ON,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 21,
        .address = REG_CH1_FRAME_FIXHEAD,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 22,
        .address = REG_CH1_FRAME_FIXHEAD_VAL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 23,
        .address = REG_CH1_CHDR_DATA,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 24,
        .address = REG_CH1_CHDR_VAL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
};

// IIO callback descriptor
static const struct iio_info h102_axi_trig_info = {
    .read_raw = h102_axi_trig_read_raw,
    .write_raw = h102_axi_trig_write_raw,
};
/*
static int h102_axi_trig_probe(struct platform_device *pdev)
{
    struct h102_state *st;
    struct iio_dev *indio_dev;
    int ret;

    // Allocate private state
    st = devm_kzalloc(&pdev->dev, sizeof(struct h102_state), GFP_KERNEL);
    if (!st)
        return -ENOMEM;

    // Get platform resources
    st->regs = devm_platform_ioremap_resource(pdev, 0);
    if (IS_ERR(st->regs))
        return PTR_ERR(st->regs);

    // Initialize the IIO device
    indio_dev = devm_iio_device_alloc(&pdev->dev, sizeof(struct h102_state));
    if (!indio_dev)
        return -ENOMEM;

    // Initialize state
    dev_set_drvdata(&pdev->dev, st);
    indio_dev->info = &h102_axi_trig_info;
    indio_dev->name = DEVICE_NAME;
    indio_dev->channels = h102_axi_trig_channels;
    indio_dev->num_channels = ARRAY_SIZE(h102_axi_trig_channels);

    // Create the IIO device
    ret = devm_iio_device_register(&pdev->dev, indio_dev);
    if (ret)
        return ret;

    // Create the attribute group
    ret = sysfs_create_group(&indio_dev->dev.kobj, &h102_axi_trig_attribute_group);
    if (ret)
        return ret;

    // Save the IIO device
    platform_set_drvdata(pdev, indio_dev);

    return 0;
}

static int h102_axi_trig_remove(struct platform_device *pdev)
{
    struct iio_dev *indio_dev = platform_get_drvdata(pdev);

    sysfs_remove_group(&indio_dev->dev.kobj, &h102_axi_trig_attribute_group);
    iio_device_unregister(indio_dev);

    return 0;
}

*/
static int h102_axi_trig_probe(struct platform_device *pdev)

{

    struct iio_dev *indio_dev;
    struct h102_state *st;
    struct resource *res;

    indio_dev = devm_iio_device_alloc(&pdev->dev, sizeof(*st));

    if (!indio_dev)

        return -ENOMEM;
    platform_set_drvdata(pdev, indio_dev);
    st = iio_priv(indio_dev);

    res = platform_get_resource(pdev, IORESOURCE_MEM, 0);

    if (!res) {
        dev_err(&pdev->dev, "Failed to get memory resource\n");
        return -ENODEV;
    }

    st->regs = devm_ioremap_resource(&pdev->dev, res);

    if (IS_ERR(st->regs)) {
        dev_err(&pdev->dev, "Failed to remap memory resource\n");
        return PTR_ERR(st->regs);

    }

    indio_dev->name = pdev->name;
    indio_dev->info = &h102_axi_trig_info;
    indio_dev->modes = INDIO_DIRECT_MODE;
    indio_dev->channels = h102_axi_trig_channels;
    indio_dev->num_channels = ARRAY_SIZE(h102_axi_trig_channels);
    return devm_iio_device_register(&pdev->dev, indio_dev);

}



static int h102_axi_trig_remove(struct platform_device *pdev)

{

    struct iio_dev *indio_dev = platform_get_drvdata(pdev);
    iio_device_unregister(indio_dev);
    return 0;

}


// Device-tree match table
static const struct of_device_id h102_axi_trig_of_match[] = {
    { .compatible = "h102,h102_axi_trig", },
    {},
};
MODULE_DEVICE_TABLE(of, h102_axi_trig_of_match);

// Platform driver
static struct platform_driver h102_axi_trig_driver = {
    .probe = h102_axi_trig_probe,
    .remove = h102_axi_trig_remove,
    .driver = {
        .name = DEVICE_NAME,
	.of_match_table = h102_axi_trig_of_match,
        .owner = THIS_MODULE,
    },
};

module_platform_driver(h102_axi_trig_driver);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("LogicRF");
MODULE_DESCRIPTION("H102 AXI Trig Driver");
