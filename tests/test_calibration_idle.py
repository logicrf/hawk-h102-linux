"""Test real source checks on regular files; bounded CAL power does not qualify RF/DMA/USB."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import h102_rf_owner as rf


def test_calibrated_idle_preserves_strict_normal_idle_and_rejects_rf_data(tmp_path):
    """Execute actual Hardware checks while modeling MMIO, without board qualification."""
    hw=object.__new__(rf.Hardware);hw.phy=tmp_path/'phy';hw.phy.mkdir();hw.fixture=tmp_path
    hw.devices={name:tmp_path/name for name in rf.DMA_NAMES};hw.alt_attributes={}
    for i in (0,1):
        (hw.phy/f'out_voltage{i}_en').write_text('1' if i==0 else '0')
        (hw.phy/f'out_voltage{i}_ensm_mode').write_text('calibrated')
    for name,path in hw.devices.items():
        (path/'buffer').mkdir(parents=True);(path/'buffer/enable').write_text('0')
    for name in rf.DDS_NAMES:
        for i in range(4):
            path=hw.devices[name]/f'raw{i}';path.write_text('0');hw.alt_attributes[(name,i,'raw')]=path
    with pytest.raises(RuntimeError,match='RF_OR_DMA_BUSY'):hw.idle()
    hw.calibration_idle()
    (hw.phy/'out_voltage0_ensm_mode').write_text('rf_enabled')
    with pytest.raises(RuntimeError,match='CALIBRATED_TX_REQUIRED'):hw.calibration_idle()
    (hw.phy/'out_voltage0_ensm_mode').write_text('calibrated')
    raw=hw.alt(rf.DDS_NAMES[0],0,'raw');raw.write_text('1')
    with pytest.raises(RuntimeError,match='RF_OR_DMA_BUSY'):hw.calibration_idle()
    raw.write_text('0');(hw.devices[rf.DMA_NAMES[0]]/'buffer/enable').write_text('1')
    with pytest.raises(RuntimeError,match='RF_OR_DMA_BUSY'):hw.calibration_idle()
