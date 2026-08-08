#!/usr/bin/env python3
"""
test_starship.py — Tests for starship-jetsonclaw1.py

Covers:
- Pure functions (read helpers, alert_color, formatting)
- Hardware readout functions (mocked sysfs/proc)
- Room creation (make_rooms)
- Starship class methods (status, scan, pulse, enter_room)
- Command parsing edge cases
- Bug fixes validated

Run: python3 -m pytest test_starship.py -v
   or python3 test_starship.py
"""

import os
import sys
import json
import tempfile
import shutil
import subprocess
from unittest.mock import patch, mock_open, MagicMock
from io import StringIO

# Ensure we can import the main module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the module — since the filename has dashes, use importlib
import importlib.util
spec = importlib.util.spec_from_file_location(
    "starship", os.path.join(os.path.dirname(os.path.abspath(__file__)), "starship-jetsonclaw1.py")
)
starship = importlib.util.module_from_spec(spec)
sys.modules['starship'] = starship
spec.loader.exec_module(starship)

# Re-export key names for convenience
C = starship.C
b = starship.b
Surprise = None  # not in this module
Room = starship.Room
Starship = starship.Starship


# ═══════════════════════════════════════════════════════════════════
# Color / formatting tests
# ═══════════════════════════════════════════════════════════════════

class TestColors:
    """Test the color system."""

    def test_b_wraps_text_with_color(self):
        result = b("hello", C.RED)
        assert C.RED in result
        assert "hello" in result
        assert result.endswith(C.RST)

    def test_b_includes_reset(self):
        result = b("test", C.GRN)
        assert result.endswith(C.RST)

    def test_b_empty_string(self):
        result = b("", C.YEL)
        assert C.YEL in result
        assert C.RST in result

    def test_all_color_codes_are_strings(self):
        """Every color constant should be a non-empty string starting with ESC."""
        for attr in dir(C):
            if not attr.startswith('_'):
                val = getattr(C, attr)
                assert isinstance(val, str), f"{attr} is not a string"
                assert val.startswith('\033['), f"{attr} = {val!r} doesn't start with ESC["

    def test_RST_is_reset(self):
        assert C.RST == '\033[0m'

    def test_BOLD_is_bold(self):
        assert C.BOLD == '\033[1m'


# ═══════════════════════════════════════════════════════════════════
# File reading helpers
# ═══════════════════════════════════════════════════════════════════

class TestReadHelpers:
    """Test read_file, read_int, read_float."""

    def test_read_file_existing(self):
        """read_file returns stripped content from a real file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("  hello world  \n")
            path = f.name
        try:
            assert starship.read_file(path) == "hello world"
        finally:
            os.unlink(path)

    def test_read_file_missing_returns_none(self):
        """read_file returns None for nonexistent paths."""
        assert starship.read_file("/nonexistent/path/to/nowhere") is None

    def test_read_file_empty_file(self):
        """read_file returns empty string for empty file (after strip)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("   \n  \n")
            path = f.name
        try:
            assert starship.read_file(path) == ""
        finally:
            os.unlink(path)

    def test_read_int_valid(self):
        """read_int returns integer from file content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("42000\n")
            path = f.name
        try:
            assert starship.read_int(path) == 42000
        finally:
            os.unlink(path)

    def test_read_int_missing_returns_zero(self):
        """read_int returns 0 for missing files."""
        assert starship.read_int("/nonexistent") == 0

    def test_read_float_valid(self):
        """read_float returns float divided by divisor."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("55000\n")
            path = f.name
        try:
            assert starship.read_float(path, div=1000.0) == 55.0
        finally:
            os.unlink(path)

    def test_read_float_default_divisor(self):
        """read_float with default divisor (1.0) returns raw value."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("42.5\n")
            path = f.name
        try:
            assert starship.read_float(path) == 42.5
        finally:
            os.unlink(path)

    def test_read_float_missing_returns_zero(self):
        """read_float returns 0.0 for missing files."""
        assert starship.read_float("/nonexistent") == 0.0


# ═══════════════════════════════════════════════════════════════════
# alert_color tests
# ═══════════════════════════════════════════════════════════════════

class TestAlertColor:
    """Test the threshold-based alert coloring."""

    def test_normal_value_is_green(self):
        """Below warn threshold, above=True → green."""
        assert starship.alert_color(30, 55, 70) == C.GRN

    def test_warn_value_is_yellow(self):
        """Between warn and crit thresholds → yellow."""
        assert starship.alert_color(60, 55, 70) == C.YEL

    def test_critical_value_is_red(self):
        """Above crit threshold → red."""
        assert starship.alert_color(80, 55, 70) == C.RED

    def test_exact_warn_threshold_is_yellow(self):
        """At exactly the warn threshold → yellow (>=)."""
        assert starship.alert_color(55, 55, 70) == C.YEL

    def test_exact_crit_threshold_is_red(self):
        """At exactly the crit threshold → red (>=)."""
        assert starship.alert_color(70, 55, 70) == C.RED

    def test_below_mode_normal_is_green(self):
        """above=False, high value → green."""
        assert starship.alert_color(5000, 1000, 500, above=False) == C.GRN

    def test_below_mode_warn_is_yellow(self):
        """above=False, between thresholds → yellow."""
        assert starship.alert_color(750, 1000, 500, above=False) == C.YEL

    def test_below_mode_crit_is_red(self):
        """above=False, below crit threshold → red."""
        assert starship.alert_color(300, 1000, 500, above=False) == C.RED


# ═══════════════════════════════════════════════════════════════════
# get_memory tests (mocked /proc/meminfo)
# ═══════════════════════════════════════════════════════════════════

class TestGetMemory:
    """Test memory parsing from /proc/meminfo."""

    MEMINFO_SAMPLE = """MemTotal:       8048120 kB
MemFree:         120340 kB
MemAvailable:   3500640 kB
Buffers:          45200 kB
Cached:         2800000 kB
SwapCached:           0 kB
Active:         2000000 kB
Inactive:        800000 kB
"""

    @patch('builtins.open', new_callable=mock_open, read_data=MEMINFO_SAMPLE)
    def test_get_memory_parses_correctly(self, mock_file):
        """get_memory correctly parses MemTotal, MemAvailable, etc."""
        mem = starship.get_memory()
        assert mem['total'] == 8048120 // 1024  # 7859 MB
        assert mem['available'] == 3500640 // 1024  # 3418 MB
        assert mem['free'] == 120340 // 1024  # 117 MB
        assert mem['buffers'] == 45200 // 1024  # 44 MB
        assert mem['cached'] == 2800000 // 1024  # 2734 MB
        assert mem['used'] == mem['total'] - mem['available']

    @patch('builtins.open', side_effect=IOError("no file"))
    def test_get_memory_failure_returns_zeros(self, mock_file):
        """When /proc/meminfo can't be read, return zeros."""
        mem = starship.get_memory()
        assert mem['total'] == 0
        assert mem['available'] == 0
        assert mem['used'] == 0

    @patch('builtins.open', new_callable=mock_open, read_data="")
    def test_get_memory_empty_file(self, mock_file):
        """Empty meminfo returns all zeros."""
        mem = starship.get_memory()
        assert mem['total'] == 0
        assert mem['available'] == 0


# ═══════════════════════════════════════════════════════════════════
# get_thermal_zones tests
# ═══════════════════════════════════════════════════════════════════

class TestThermalZones:
    """Test thermal zone reading (mocked sysfs)."""

    def test_get_thermal_zones_parses_correctly(self):
        """Thermal zones are read and temperatures converted to Celsius."""
        with patch('os.listdir', return_value=['thermal_zone0', 'thermal_zone1', 'eth0']), \
             patch('starship.read_file', side_effect=[
                 "45000\n",    # zone0 temp
                 "CPU\n",      # zone0 type (not used by get_thermal_zones itself)
                 "38000\n",    # zone1 temp
                 "GPU\n",      # zone1 type
             ]), \
             patch('starship.read_int', side_effect=[45000, 38000]):
            zones = starship.get_thermal_zones()
            assert len(zones) == 2
            assert zones[0] == (0, 45.0)
            assert zones[1] == (1, 38.0)

    def test_get_thermal_zones_empty(self):
        """No thermal zones returns empty list."""
        with patch('os.listdir', return_value=[]):
            zones = starship.get_thermal_zones()
            assert zones == []

    def test_get_thermal_zones_filters_zero_temp(self):
        """Zones with temp=0 are skipped (sensor not populated)."""
        with patch('os.listdir', return_value=['thermal_zone0', 'thermal_zone1']), \
             patch('starship.read_int', side_effect=[0, 45000]):
            zones = starship.get_thermal_zones()
            assert len(zones) == 1
            assert zones[0] == (1, 45.0)


# ═══════════════════════════════════════════════════════════════════
# get_interfaces tests
# ═══════════════════════════════════════════════════════════════════

class TestGetInterfaces:
    """Test network interface scanning."""

    def test_get_interfaces_excludes_loopback(self):
        """Loopback interface 'lo' should be excluded."""
        with patch('os.listdir', return_value=['lo', 'eth0']):
            with patch('starship.read_file', return_value='up'):
                with patch('starship.read_int', return_value=1024):
                    ifaces = starship.get_interfaces()
                    names = [i['name'] for i in ifaces]
                    assert 'lo' not in names
                    assert 'eth0' in names

    def test_get_interfaces_parses_state(self):
        """Interface up/down state is correctly parsed."""
        # get_interfaces calls read_file for operstate and read_int for rx+tx bytes per interface
        with patch('os.listdir', return_value=['eth0', 'wlan0']), \
             patch('starship.read_file', side_effect=['up', 'down']), \
             patch('starship.read_int', side_effect=[1048576, 65536, 32768, 16384]):
            ifaces = starship.get_interfaces()
            assert len(ifaces) == 2
            eth0 = ifaces[0]
            assert eth0['name'] == 'eth0'
            assert eth0['up'] is True
            assert eth0['rx_kb'] == 1048576 // 1024  # 1024 KB

    def test_get_interfaces_empty(self):
        """No interfaces returns empty list."""
        with patch('os.listdir', return_value=[]):
            ifaces = starship.get_interfaces()
            assert ifaces == []


# ═══════════════════════════════════════════════════════════════════
# Room and Starship tests
# ═══════════════════════════════════════════════════════════════════

class TestRoom:
    """Test the Room class."""

    def test_room_creation(self):
        room = Room("Test Room", "A test room.", lambda: "test output", ["exit1"])
        assert room.name == "Test Room"
        assert room.short_desc == "A test room."
        assert room.examine_fn() == "test output"
        assert room.exits == ["exit1"]

    def test_room_default_exits(self):
        room = Room("Test", "Desc", lambda: "")
        assert room.exits == []


class TestMakeRooms:
    """Test that make_rooms creates all expected rooms."""

    def setup_method(self):
        self.rooms = starship.make_rooms()

    def test_all_rooms_present(self):
        expected = {
            "bridge", "tactical", "engine-room", "life-support",
            "cargo-bay", "sickbay", "holodeck", "science-lab",
            "airlock", "quarterdeck"
        }
        assert set(self.rooms.keys()) == expected

    def test_room_names_are_correct(self):
        assert self.rooms["bridge"].name == "Bridge"
        assert self.rooms["tactical"].name == "Tactical"
        assert self.rooms["engine-room"].name == "Engine Room"
        assert self.rooms["life-support"].name == "Life Support"
        assert self.rooms["cargo-bay"].name == "Cargo Bay"
        assert self.rooms["sickbay"].name == "Sickbay"
        assert self.rooms["holodeck"].name == "Holodeck"
        assert self.rooms["science-lab"].name == "Science Lab"
        assert self.rooms["airlock"].name == "Airlock"
        assert self.rooms["quarterdeck"].name == "Quarterdeck"

    def test_each_room_has_desc(self):
        for room_id, room in self.rooms.items():
            assert isinstance(room.short_desc, str)
            assert len(room.short_desc) > 0, f"{room_id} has empty description"

    def test_each_room_has_examine_fn(self):
        for room_id, room in self.rooms.items():
            assert callable(room.examine_fn), f"{room_id} has no examine_fn"

    def test_bridge_examine_returns_string(self):
        """Bridge examine function should produce non-empty output."""
        with patch('starship.get_load', return_value=("0.5", "0.3", "0.2")), \
             patch('starship.get_running_agents', return_value=3), \
             patch('starship.get_uptime', return_value="5h 30m"):
            output = self.rooms["bridge"].examine_fn()
            assert isinstance(output, str)
            assert "BRIDGE" in output
            assert "Uptime" in output
            assert "CPU Load" in output


class TestStarship:
    """Test the Starship class."""

    def setup_method(self):
        self.ship = Starship()

    def test_initial_room_is_bridge(self):
        """Ship starts at the bridge."""
        assert self.ship.current == "bridge"

    def test_running_is_true_initially(self):
        assert self.ship.running is True

    def test_rooms_populated(self):
        assert len(self.ship.rooms) == 10

    def test_enter_valid_room(self):
        """enter_room changes current room."""
        warnings = self.ship.enter_room("engine-room")
        assert self.ship.current == "engine-room"
        assert isinstance(warnings, list)

    def test_enter_room_returns_warnings_list(self):
        """enter_room always returns a list (even if empty)."""
        warnings = self.ship.enter_room("bridge")
        assert isinstance(warnings, list)

    @patch('starship.get_gpu_temp', return_value=80.0)
    def test_engine_room_overheat_warning(self, mock_temp):
        """Entering engine room with GPU > 75°C triggers warning."""
        warnings = self.ship.enter_room("engine-room")
        assert len(warnings) > 0
        assert any("hot" in w.lower() or "WARNING" in w for w in warnings)

    @patch('starship.get_gpu_temp', return_value=50.0)
    def test_engine_room_normal_no_warning(self, mock_temp):
        """Entering engine room with cool GPU produces no warning."""
        warnings = self.ship.enter_room("engine-room")
        assert len(warnings) == 0

    @patch('starship.get_thermal_zones', return_value=[(0, 85.0), (1, 40.0)])
    @patch('starship.read_file', return_value="CPU")
    def test_life_support_overheat_warning(self, mock_file, mock_zones):
        """Entering life support with zone > 80°C triggers warning."""
        warnings = self.ship.enter_room("life-support")
        assert len(warnings) > 0

    @patch('starship.get_thermal_zones', return_value=[(0, 40.0)])
    @patch('starship.read_file', return_value="CPU")
    def test_life_support_normal_no_warning(self, mock_file, mock_zones):
        """Entering life support with normal temps produces no warning."""
        warnings = self.ship.enter_room("life-support")
        assert len(warnings) == 0

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[])
    @patch('starship.get_interfaces', return_value=[])
    @patch('starship.get_running_agents', return_value=5)
    @patch('starship.get_uptime', return_value="2h 15m")
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=25)
    def test_status_returns_string(self, *mocks):
        """status() returns a formatted string."""
        mocks[6].return_value = {  # get_memory mock
            'total': 8000, 'available': 4000, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 4000
        }
        result = self.ship.status()
        assert isinstance(result, str)
        assert "STATUS REPORT" in result
        assert "USS JETSONCLAW1" in result

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[(0, 45.0)])
    @patch('starship.get_interfaces', return_value=[{"name": "eth0", "up": True, "rx_kb": 1024, "tx_kb": 512}])
    @patch('starship.get_load', return_value=("0.3", "0.2", "0.1"))
    @patch('starship.get_gpu_temp', return_value=42.0)
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=15)
    def test_scan_returns_string(self, *mocks):
        """scan() returns diagnostic output."""
        mocks[6].return_value = {
            'total': 8000, 'available': 4000, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 4000
        }
        result = self.ship.scan()
        assert isinstance(result, str)
        assert "DIAGNOSTIC" in result
        assert "CPU" in result
        assert "MEMORY" in result

    def test_pulse_format(self):
        """pulse() returns compact nav-style readout."""
        with patch('starship.get_gpu_temp', return_value=45.0), \
             patch('starship.get_memory', return_value={
                 'total': 8000, 'available': 4000, 'free': 1000,
                 'buffers': 200, 'cached': 2800, 'used': 4000
             }), \
             patch('starship.get_cpu_pct', return_value=20):
            result = self.ship.pulse()
            assert isinstance(result, str)
            assert "HDG:" in result
            assert "SPD:" in result
            assert "GPU:" in result
            assert "RAM:" in result
            assert "CPU:" in result

    @patch('starship.get_cpu_pct', return_value=0)
    @patch('starship.get_memory')
    @patch('starship.get_gpu_temp', return_value=None)
    def test_pulse_no_gpu_temp(self, mock_gpu, mock_mem, mock_cpu):
        """pulse() handles None GPU temp gracefully."""
        mock_mem.return_value = {
            'total': 8000, 'available': 500, 'free': 100,
            'buffers': 0, 'cached': 0, 'used': 7500
        }
        result = self.ship.pulse()
        assert "??" in result  # No GPU temp → ??

    def test_compass_cmd(self):
        result = self.ship.compass_cmd()
        assert "compass" in result.lower()
        assert isinstance(result, str)

    def test_gps_cmd(self):
        result = self.ship.gps_cmd()
        assert "gps" in result.lower() or "GPS" in result
        assert isinstance(result, str)

    def test_depth_cmd(self):
        result = self.ship.depth_cmd()
        assert "depth" in result.lower()
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════
# Fleet / Imagine tests (network mocked)
# ═══════════════════════════════════════════════════════════════════

class TestFleet:
    """Test fleet command with mocked network."""

    def test_fleet_offline_returns_message(self):
        """When wheelhouse-api is unreachable, returns offline message."""
        with patch('urllib.request.urlopen', side_effect=ConnectionRefusedError("refused")):
            result = self.ship.fleet()
            assert "offline" in result.lower()

    def setup_method(self):
        self.ship = Starship()

    def test_fleet_success(self):
        """Fleet command formats JSON response correctly."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "sensor_a": {"temp": 42.0, "humidity": 55.0},
            "sensor_b": {"pressure": 1013}
        }).encode()
        with patch('urllib.request.urlopen', return_value=mock_response):
            result = self.ship.fleet()
            assert "FLEET SENSOR" in result
            assert "SENSOR_A" in result

    def test_fleet_timeout(self):
        """Fleet command handles timeout gracefully."""
        with patch('urllib.request.urlopen', side_effect=TimeoutError("timed out")):
            result = self.ship.fleet()
            assert "offline" in result.lower()

    def test_fleet_json_error(self):
        """Fleet command handles invalid JSON."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json at all"
        with patch('urllib.request.urlopen', return_value=mock_response):
            result = self.ship.fleet()
            # Should either show offline or error — not crash
            assert isinstance(result, str)


class TestImagine:
    """Test the holodeck imagine command."""

    def setup_method(self):
        self.ship = Starship()

    def test_imagine_offline(self):
        """Imagine returns offline message when seed-mcp is down."""
        with patch('urllib.request.urlopen', side_effect=ConnectionRefusedError("refused")):
            result = self.ship.imagine("a beautiful sunset")
            assert "offline" in result.lower()

    def test_imagine_success(self):
        """Imagine formats response from seed-mcp."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"text": "A canvas of impossible colors"}]
        }).encode()
        with patch('urllib.request.urlopen', return_value=mock_response):
            result = self.ship.imagine("sunset on mars")
            assert "HOLODECK" in result
            assert "A canvas" in result

    def test_imagine_timeout(self):
        """Imagine handles timeout gracefully."""
        with patch('urllib.request.urlopen', side_effect=TimeoutError("timed out")):
            result = self.ship.imagine("test")
            assert isinstance(result, str)
            assert "offline" in result.lower() or "error" in result.lower()


# ═══════════════════════════════════════════════════════════════════
# get_uptime / get_load / get_cpu_pct tests
# ═══════════════════════════════════════════════════════════════════

class TestSystemInfo:
    """Test system information functions."""

    @patch('builtins.open', new_callable=mock_open, read_data="3600.5 12000.0\n")
    def test_get_uptime_one_hour(self, mock_file):
        result = starship.get_uptime()
        assert "1h" in result
        assert "0m" in result

    @patch('builtins.open', new_callable=mock_open, read_data="90061.0 12000.0\n")
    def test_get_uptime_one_day_plus(self, mock_file):
        """25 hours → '25h 1m'."""
        result = starship.get_uptime()
        assert "25h" in result
        assert "1m" in result

    @patch('builtins.open', side_effect=IOError("nope"))
    def test_get_uptime_error(self, mock_file):
        assert starship.get_uptime() == "unknown"

    @patch('builtins.open', new_callable=mock_open, read_data="0.50 0.35 0.25 1/100 12345\n")
    def test_get_load_parses(self, mock_file):
        l1, l5, l15 = starship.get_load()
        assert l1 == "0.50"
        assert l5 == "0.35"
        assert l15 == "0.25"

    @patch('builtins.open', side_effect=IOError("nope"))
    def test_get_load_error(self, mock_file):
        l1, l5, l15 = starship.get_load()
        assert (l1, l5, l15) == ("0", "0", "0")

    @patch('builtins.open', new_callable=mock_open, read_data="3.20 0.35 0.25 1/100 12345\n")
    def test_get_cpu_pct_caps_at_100(self, mock_file):
        """CPU pct should cap at 100 even with load > 4."""
        result = starship.get_cpu_pct()
        assert result <= 100

    @patch('builtins.open', new_callable=mock_open, read_data="2.00 0.35 0.25 1/100 12345\n")
    def test_get_cpu_pct_normal(self, mock_file):
        """Load of 2.0 / 4 cores → 50%."""
        result = starship.get_cpu_pct()
        assert result == 50

    @patch('builtins.open', side_effect=IOError("nope"))
    def test_get_cpu_pct_error(self, mock_file):
        assert starship.get_cpu_pct() == 0


# ═══════════════════════════════════════════════════════════════════
# get_gpu_temp / get_gpu_freq / get_power_mode tests
# ═══════════════════════════════════════════════════════════════════

class TestGpuInfo:

    def test_get_gpu_temp_finds_gpu_zone(self):
        """get_gpu_temp returns temperature from GPU thermal zone."""
        with patch('starship.get_thermal_zones', return_value=[(0, 45.0), (1, 55.0)]), \
             patch('starship.read_file', return_value="GPU"):
            result = starship.get_gpu_temp()
            # Should return temp from zone with type "GPU"
            # The function iterates zones and checks type
            assert result is not None

    def test_get_gpu_temp_no_gpu_zone(self):
        """get_gpu_temp returns None when no GPU zone found."""
        with patch('starship.get_thermal_zones', return_value=[(0, 45.0)]), \
             patch('starship.read_file', return_value="CPU"):
            result = starship.get_gpu_temp()
            assert result is None

    @patch('starship.read_int', return_value=921600000)
    def test_get_gpu_freq_converts(self, mock_read):
        """GPU freq of 921600000 → 921 MHz."""
        result = starship.get_gpu_freq()
        assert result == 921  # 921600000 // 1000000 = 921

    @patch('starship.read_int', return_value=0)
    def test_get_gpu_freq_zero(self, mock_read):
        """GPU freq of 0 → 0."""
        assert starship.get_gpu_freq() == 0

    @patch('starship.read_file', return_value="MAXN")
    def test_get_power_mode_reads_file(self, mock_read):
        assert starship.get_power_mode() == "MAXN"

    @patch('starship.read_file', return_value=None)
    def test_get_power_mode_unknown(self, mock_read):
        """When all reads return None, returns 'unknown'."""
        # get_power_mode tries two paths, both return None
        # The `or` chain falls through to "unknown"
        assert starship.get_power_mode() == "unknown"


# ═══════════════════════════════════════════════════════════════════
# format_status_bar tests
# ═══════════════════════════════════════════════════════════════════

class TestFormatStatusBar:

    @patch('starship.get_gpu_temp', return_value=48.0)
    @patch('starship.get_memory')
    @patch('starship.get_cpu_pct', return_value=30)
    def test_format_status_bar_normal(self, mock_cpu, mock_mem, mock_gpu):
        mock_mem.return_value = {
            'total': 8000, 'available': 4096, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 3904
        }
        result = starship.format_status_bar()
        assert "GPU:" in result
        assert "48°C" in result
        assert "RAM:" in result
        assert "CPU:" in result
        assert "30%" in result

    @patch('starship.get_gpu_temp', return_value=None)
    @patch('starship.get_memory')
    @patch('starship.get_cpu_pct', return_value=0)
    def test_format_status_bar_no_gpu(self, mock_cpu, mock_mem, mock_gpu):
        mock_mem.return_value = {
            'total': 8000, 'available': 500, 'free': 100,
            'buffers': 0, 'cached': 0, 'used': 7500
        }
        result = starship.format_status_bar()
        assert "N/A" in result
        assert "500MB" in result  # Below 1024 → MB format


# ═══════════════════════════════════════════════════════════════════
# get_running_agents tests
# ═══════════════════════════════════════════════════════════════════

class TestRunningAgents:

    @patch('subprocess.run')
    def test_get_running_agents_counts(self, mock_run):
        mock_run.return_value = MagicMock(stdout="5\n")
        result = starship.get_running_agents()
        assert result == 5

    @patch('subprocess.run')
    def test_get_running_agents_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="\n")
        result = starship.get_running_agents()
        assert result == 0

    @patch('subprocess.run', side_effect=FileNotFoundError("no pgrep"))
    def test_get_running_agents_no_pgrep(self, mock_run):
        assert starship.get_running_agents() == 0


# ═══════════════════════════════════════════════════════════════════
# Integration: Starship scan for anomalies
# ═══════════════════════════════════════════════════════════════════

class TestScanAnomalies:
    """Test that scan() correctly detects and reports anomalies."""

    def setup_method(self):
        self.ship = Starship()

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[(0, 45.0)])
    @patch('starship.get_interfaces', return_value=[])
    @patch('starship.get_load', return_value=("0.3", "0.2", "0.1"))
    @patch('starship.get_gpu_temp', return_value=42.0)
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=15)
    def test_scan_all_nominal(self, *mocks):
        mocks[6].return_value = {
            'total': 8000, 'available': 4000, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 4000
        }
        result = self.ship.scan()
        assert "NOMINAL" in result
        assert "ANOMALIES" not in result

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[(0, 45.0)])
    @patch('starship.get_interfaces', return_value=[])
    @patch('starship.get_load', return_value=("0.3", "0.2", "0.1"))
    @patch('starship.get_gpu_temp', return_value=75.0)  # GPU overheat
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=15)
    def test_scan_detects_gpu_overheat(self, *mocks):
        mocks[6].return_value = {
            'total': 8000, 'available': 4000, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 4000
        }
        result = self.ship.scan()
        assert "ANOMALIES" in result
        assert "ENGINE OVERHEAT" in result

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[(0, 85.0)])  # Thermal critical
    @patch('starship.get_interfaces', return_value=[])
    @patch('starship.get_load', return_value=("0.3", "0.2", "0.1"))
    @patch('starship.get_gpu_temp', return_value=42.0)
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=15)
    def test_scan_detects_thermal_critical(self, *mocks):
        mocks[6].return_value = {
            'total': 8000, 'available': 4000, 'free': 1000,
            'buffers': 200, 'cached': 2800, 'used': 4000
        }
        result = self.ship.scan()
        assert "ANOMALIES" in result
        assert "THERMAL CRITICAL" in result

    @patch('starship.get_memory')
    @patch('starship.get_thermal_zones', return_value=[(0, 45.0)])
    @patch('starship.get_interfaces', return_value=[])
    @patch('starship.get_load', return_value=("0.3", "0.2", "0.1"))
    @patch('starship.get_gpu_temp', return_value=42.0)
    @patch('starship.get_gpu_freq', return_value=614)
    @patch('starship.get_cpu_pct', return_value=15)
    def test_scan_detects_memory_critical(self, *mocks):
        mocks[6].return_value = {
            'total': 8000, 'available': 300, 'free': 50,
            'buffers': 0, 'cached': 0, 'used': 7700
        }
        result = self.ship.scan()
        assert "MEMORY CRITICAL" in result


# ═══════════════════════════════════════════════════════════════════
# Run with unittest if pytest not available
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Try pytest first, fall back to unittest
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        import unittest
        unittest.main()
