import psutil
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class HardwareContext:
    def __init__(self):
        self.ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        self.cpu_cores = psutil.cpu_count(logical=False) or 2
        self.logical_cores = psutil.cpu_count(logical=True) or 2
        
    def get_profile(self) -> Dict[str, Any]:
        """Returns the hardware profile and appropriate concurrency limits."""
        
        # Determine aggressiveness tier
        if self.ram_gb >= 24:
            tier = "High"
            max_concurrent_scans = self.logical_cores
            enable_load_testing = True
            load_test_max_rps = 1000
        elif self.ram_gb >= 12:
            tier = "Mid"
            max_concurrent_scans = max(2, self.logical_cores // 2)
            enable_load_testing = True
            load_test_max_rps = 100
        else:
            tier = "Low"
            max_concurrent_scans = 1
            enable_load_testing = False
            load_test_max_rps = 0

        logger.info(f"Hardware Context Profile detected: {tier} (RAM: {self.ram_gb:.1f}GB, Cores: {self.logical_cores})")
            
        return {
            "tier": tier,
            "ram_gb": round(self.ram_gb, 2),
            "cpu_cores": self.logical_cores,
            "max_concurrent_scans": max_concurrent_scans,
            "enable_load_testing": enable_load_testing,
            "load_test_max_rps": load_test_max_rps
        }

hardware_context = HardwareContext()
