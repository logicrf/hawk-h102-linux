#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/io.h>
#include <linux/iio/iio.h>
#include <linux/iio/sysfs.h>
#include <linux/iio/types.h>
#include <linux/iio/driver.h>

#define DEVICE_NAME "h102_axi_reg"

// Register offsets
enum h102_axi_reg_registers {
    REG_HW_VER = 0x00,
    REG_RTL_VER = 0x04,
    REG_RSV_VER = 0x08,

    //0x10~0x15
    REG_ADRV9002_RTX_EN = 0x40,
    REG_AD9528_REFSEL = 0x44,
    REG_USB_PATH_SEL = 0x48,
    REG_RS422_DE_REN = 0x4C,
    REG_RS485_DE = 0x50,
    REG_REFIN_PPS_SEL = 0x54,
    //CH0-0x20~0x21
    REG_RF_CTRL_IO = 0x80,
    REG_RF_CTRL_DIR = 0x84,
    //CH1-0x30~0x33
    REG_MCU_VERSION = 0xC0,
    REG_MCU_VOLT = 0xC4,
    REG_MCU_CURR = 0xC8,
    REG_FAN_STATUS = 0xCC,
};

struct h102_state {
    void __iomem        *regs;
    struct mutex		lock;
};


void h102_axi_reg_write(struct h102_state *st,unsigned int reg, unsigned int val)
{
	iowrite32(val, st->regs + reg);
}


int h102_axi_reg_read(struct h102_state *st, unsigned int reg)
{
	return ioread32(st->regs + reg);
}


// Read register value
static ssize_t h102_axi_reg_show(struct device *dev,
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
    else if (strcmp(attr->attr.name, "adrv9002_rtx_en") == 0)
        val = ioread32(st->regs + REG_ADRV9002_RTX_EN);
    else if (strcmp(attr->attr.name, "ad9528_refsel") == 0)
        val = ioread32(st->regs + REG_AD9528_REFSEL);
    else if (strcmp(attr->attr.name, "usb_path_sel") == 0)
        val = ioread32(st->regs + REG_USB_PATH_SEL);
    else if (strcmp(attr->attr.name, "rs422_de_ren") == 0)
        val = ioread32(st->regs + REG_RS422_DE_REN);                        
    else if (strcmp(attr->attr.name, "rs485_de") == 0)
        val = ioread32(st->regs + REG_RS485_DE);
    else if (strcmp(attr->attr.name, "refin_pps_sel") == 0)
        val = ioread32(st->regs + REG_REFIN_PPS_SEL);
    else if (strcmp(attr->attr.name, "rf_ctrl_io") == 0)
        val = ioread32(st->regs + REG_RF_CTRL_IO);
    else if (strcmp(attr->attr.name, "rf_ctrl_dir") == 0)
        val = ioread32(st->regs + REG_RF_CTRL_DIR); 
    else if (strcmp(attr->attr.name, "mcu_version") == 0)
        val = ioread32(st->regs + REG_MCU_VERSION);
    else if (strcmp(attr->attr.name, "mcu_volt") == 0)
        val = ioread32(st->regs + REG_MCU_VOLT); 
    else if (strcmp(attr->attr.name, "mcu_curr") == 0)
        val = ioread32(st->regs + REG_MCU_CURR);
    else if (strcmp(attr->attr.name, "fan_status") == 0)
        val = ioread32(st->regs + REG_FAN_STATUS); 
    else
        return -EINVAL;

    return len;
}


// Write register value
static ssize_t h102_axi_reg_store(struct device *dev,
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

    if (strcmp(attr->attr.name, "adrv9002_rtx_en") == 0)
        iowrite32(val, st->regs + REG_ADRV9002_RTX_EN);
    else if (strcmp(attr->attr.name, "ad9528_refsel") == 0)
        iowrite32(val, st->regs + REG_AD9528_REFSEL);
    else if (strcmp(attr->attr.name, "usb_path_sel") == 0)
        iowrite32(val, st->regs + REG_USB_PATH_SEL);
    else if (strcmp(attr->attr.name, "rs422_de_ren") == 0)
        iowrite32(val, st->regs + REG_RS422_DE_REN);                        
    else if (strcmp(attr->attr.name, "rs485_de") == 0)
        iowrite32(val, st->regs + REG_RS485_DE);
    else if (strcmp(attr->attr.name, "refin_pps_sel") == 0)
        iowrite32(val, st->regs + REG_REFIN_PPS_SEL);
    else if (strcmp(attr->attr.name, "rf_ctrl_io") == 0)
        iowrite32(val, st->regs + REG_RF_CTRL_IO);
    else if (strcmp(attr->attr.name, "rf_ctrl_dir") == 0)
        iowrite32(val, st->regs + REG_RF_CTRL_DIR); 
    else
        return -EINVAL;


    return count;
}

// IIO attribute definitions
static IIO_DEVICE_ATTR(hw_ver, S_IRUGO, h102_axi_reg_show, NULL, 0);
static IIO_DEVICE_ATTR(rtl_ver, S_IRUGO, h102_axi_reg_show, NULL, 1);
static IIO_DEVICE_ATTR(rsv_ver, S_IRUGO, h102_axi_reg_show, NULL, 2);

static IIO_DEVICE_ATTR(adrv9002_rtx_en,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 3);
static IIO_DEVICE_ATTR(ad9528_refsel,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 4);
static IIO_DEVICE_ATTR(usb_path_sel,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 5);
static IIO_DEVICE_ATTR(rs422_de_ren,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 6);

static IIO_DEVICE_ATTR(rs485_de,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 7);
static IIO_DEVICE_ATTR(refin_pps_sel,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 8);
static IIO_DEVICE_ATTR(rf_ctrl_io,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 9);
static IIO_DEVICE_ATTR(rf_ctrl_dir,S_IRUGO|S_IWUSR, h102_axi_reg_show, h102_axi_reg_store, 10);

static IIO_DEVICE_ATTR(mcu_version, S_IRUGO, h102_axi_reg_show, NULL, 11);
static IIO_DEVICE_ATTR(mcu_volt, S_IRUGO, h102_axi_reg_show, NULL, 12);
static IIO_DEVICE_ATTR(mcu_curr, S_IRUGO, h102_axi_reg_show, NULL, 13);
static IIO_DEVICE_ATTR(fan_status, S_IRUGO, h102_axi_reg_show, NULL, 14);

// Register IIO attributes
static struct attribute *h102_axi_reg_attributes[] = {
    &iio_dev_attr_hw_ver.dev_attr.attr,
    &iio_dev_attr_rtl_ver.dev_attr.attr,
    &iio_dev_attr_rsv_ver.dev_attr.attr,
    &iio_dev_attr_adrv9002_rtx_en.dev_attr.attr,
    &iio_dev_attr_ad9528_refsel.dev_attr.attr,
    &iio_dev_attr_usb_path_sel.dev_attr.attr,
    &iio_dev_attr_rs422_de_ren.dev_attr.attr,
    &iio_dev_attr_rs485_de.dev_attr.attr,
    &iio_dev_attr_refin_pps_sel.dev_attr.attr,
    &iio_dev_attr_rf_ctrl_io.dev_attr.attr,
    &iio_dev_attr_rf_ctrl_dir.dev_attr.attr,
    &iio_dev_attr_mcu_version.dev_attr.attr,
    &iio_dev_attr_mcu_volt.dev_attr.attr,
    &iio_dev_attr_mcu_curr.dev_attr.attr,
    &iio_dev_attr_fan_status.dev_attr.attr,
    NULL,
};



static const struct attribute_group h102_axi_reg_attribute_group = {
    .attrs = h102_axi_reg_attributes,
};

static int h102_axi_reg_read_raw(struct iio_dev *indio_dev,
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
        pr_err("h102_axi_reg_read_raw: Null pointer detected, st=%p, st->reg=%p\n", st, st ? st->regs : NULL);
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

static int h102_axi_reg_write_raw(struct iio_dev *indio_dev,
                                  struct iio_chan_spec const *chan,
                                  int val,
                                  int val2,
                                  long mask)
{
    struct h102_state *st = iio_priv(indio_dev);

    // Trace register access
    if (!st || !st->regs)
    {
        pr_err("h102_axi_reg_show: Null pointer detected, st=%p, st->reg=%p\n", st, st ? st->regs : NULL);
        return -EINVAL;
    }

    if(chan->output){
        iowrite32(val, st->regs + chan->address);
        return 0; 
    }else{
        return -EINVAL;
    }
}


static const struct iio_chan_spec h102_axi_reg_channels[] = {
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
        .address = REG_ADRV9002_RTX_EN,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 4,
        .address = REG_AD9528_REFSEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 5,
        .address = REG_USB_PATH_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },    

    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 6,
        .address = REG_RS422_DE_REN,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },


    // ch0
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 7,
        .address = REG_RS485_DE,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 8,
        .address = REG_REFIN_PPS_SEL,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 9,
        .address = REG_RF_CTRL_IO,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .output = 1,
        .channel = 10,
        .address = REG_RF_CTRL_DIR,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 11,
        .address = REG_MCU_VERSION,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 12,
        .address = REG_MCU_VOLT,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 13,
        .address = REG_MCU_CURR,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
    {
        .type = IIO_VOLTAGE,
        .indexed = 1,
        .channel = 14,
        .address = REG_FAN_STATUS,
        .info_mask_separate = BIT(IIO_CHAN_INFO_RAW),
    },
};

// IIO callback descriptor
static const struct iio_info h102_axi_reg_info = {
    .read_raw = h102_axi_reg_read_raw,
    .write_raw = h102_axi_reg_write_raw,
};

static int h102_axi_reg_probe(struct platform_device *pdev)
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
    indio_dev->info = &h102_axi_reg_info;
    indio_dev->modes = INDIO_DIRECT_MODE;
    indio_dev->channels = h102_axi_reg_channels;
    indio_dev->num_channels = ARRAY_SIZE(h102_axi_reg_channels);
    return devm_iio_device_register(&pdev->dev, indio_dev);

}



static int h102_axi_reg_remove(struct platform_device *pdev)
{
    struct iio_dev *indio_dev = platform_get_drvdata(pdev);
    iio_device_unregister(indio_dev);
    return 0;
}


// Device-tree match table
static const struct of_device_id h102_axi_reg_of_match[] = {
    { .compatible = "h102,h102_axi_reg", },
    {},
};
MODULE_DEVICE_TABLE(of, h102_axi_reg_of_match);

// Platform driver
static struct platform_driver h102_axi_reg_driver = {
    .probe = h102_axi_reg_probe,
    .remove = h102_axi_reg_remove,
    .driver = {
        .name = DEVICE_NAME,
	.of_match_table = h102_axi_reg_of_match,
        .owner = THIS_MODULE,
    },
};

module_platform_driver(h102_axi_reg_driver);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("LogicRF");
MODULE_DESCRIPTION("H102 AXI Regs Driver");
