"""Offline tests for WhatMobile URL rules and its single-page scraper."""
from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "backend" / "scrapers" / "www.whatmobile.com.pk.py"
NAV_PATH = ROOT / "backend" / "navigation_to_page" / "www.whatmobile.com.pk.py"
FILTER_PATH = ROOT / "filestorage" / "FilterMobileUrls.py"
spec = importlib.util.spec_from_file_location("whatmobile_scraper_test", PATH)
module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
nav_spec = importlib.util.spec_from_file_location("whatmobile_nav_test", NAV_PATH)
nav = importlib.util.module_from_spec(nav_spec); sys.modules[nav_spec.name] = nav; nav_spec.loader.exec_module(nav)
filter_spec = importlib.util.spec_from_file_location("whatmobile_filter_test", FILTER_PATH)
mobile_filter = importlib.util.module_from_spec(filter_spec); sys.modules[filter_spec.name] = mobile_filter; filter_spec.loader.exec_module(mobile_filter)

HTML = '''<h1 class="hdng3">Example Phone X</h1><table class="specs">
<tr><td>Build</td><td>OS</td><td>Android 15</td></tr><tr><td>Dimensions</td><td>160 x 70 mm</td></tr>
<tr><td>Weight</td><td>180 g</td></tr><tr><td>SIM</td><td>Dual SIM</td></tr><tr><td>Colors</td><td>Black, Blue</td></tr>
<tr><td>Frequency</td><td>2G Band</td><td>GSM</td></tr><tr><td>3G Band</td><td>HSPA</td></tr><tr><td>4G Band</td><td>LTE</td></tr><tr><td>5G Band</td><td>SA/NSA</td></tr>
<tr><td>Processor</td><td>CPU</td><td>Octa-core</td></tr><tr><td>Chipset</td><td>Test Chip</td></tr><tr><td>GPU</td><td>Test GPU</td></tr>
<tr><td>Display</td><td>Technology</td><td>AMOLED</td></tr><tr><td>Size</td><td>6.7 Inches</td></tr><tr><td>Resolution</td><td>1080 x 2400</td></tr>
<tr><td>Memory</td><td>Built-in</td><td>256GB, 12GB RAM</td></tr><tr><td>Card</td><td>No</td></tr>
<tr><td>Camera</td><td>Main</td><td>50 MP + 8 MP</td></tr><tr><td>Features</td><td>HDR, Video (4K@30fps)</td></tr><tr><td>Front</td><td>16 MP, Video (1080p@30fps)</td></tr>
<tr><td>Connectivity</td><td>WLAN</td><td>Wi-Fi 6</td></tr><tr><td>Bluetooth</td><td>v5.3</td></tr><tr><td>GPS</td><td>Yes</td></tr><tr><td>NFC</td><td>Yes</td></tr><tr><td>Radio</td><td>No</td></tr><tr><td>USB</td><td>USB Type-C</td></tr>
<tr><td>Features</td><td>Sensors</td><td>Fingerprint (under display), gyro</td></tr><tr><td>Battery</td><td>Capacity</td><td>5000 mAh</td></tr><tr><td></td><td>- Fast battery 45W wired, 15W wireless</td></tr></table><p>Price in Rs: 99,999</p>'''

class ScraperTests(unittest.TestCase):
    def test_template_mapping(self):
        result = module.WhatmobileScraper(HTML).to_template()
        self.assertEqual(result["MobileName"], "Example Phone X")
        self.assertEqual(result["Network"], {"2G": 1, "3G": 1, "4G": 1, "5G": 1})
        self.assertEqual(result["Platform"]["Chipset"], "Test Chip")
        self.assertEqual(result["Colors"], ["Black", "Blue"])
        self.assertEqual(result["Price"], [99999.0])

class PipelineRuleTests(unittest.TestCase):
    product = "https://www.whatmobile.com.pk/Samsung_Galaxy-A57"
    catalog = "https://www.whatmobile.com.pk/Samsung_Mobiles_Prices"
    def test_product_and_catalog_rules_reject_keyword_noise(self):
        self.assertTrue(nav.whatmobile_product_match(self.product))
        self.assertFalse(nav.whatmobile_product_match(self.catalog))
        self.assertTrue(nav.whatmobile_catalog_match(self.catalog))
        self.assertFalse(nav.whatmobile_catalog_match("https://www.whatmobile.com.pk/StolenMobile.php"))
        self.assertTrue(mobile_filter.whatmobile_product_match(self.product))
        self.assertTrue(mobile_filter.whatmobile_catalog_match(self.catalog))
    def test_range_is_inclusive_and_validated(self):
        self.assertEqual(nav.resolve_range(101, None, 5), (101, 105))
        with self.assertRaises(ValueError): nav.resolve_range(5, 4, None)

if __name__ == "__main__": unittest.main()
