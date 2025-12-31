"""
Test script demonstrating the full compliance loader flow

This script shows:
1. Module discovery
2. Module activation
3. Prompt enhancement
4. Multi-module layering
5. Control resolution
"""

import sys
from pathlib import Path

# Add IHIM to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from compliance.loader import ComplianceLoader

def test_basic_flow():
    """Test basic compliance loader functionality."""
    print("=" * 70)
    print("TEST 1: Basic Loader Flow")
    print("=" * 70)

    loader = ComplianceLoader()

    # Discover available modules
    print("\n1. Discovering modules...")
    modules = loader.discover_modules()
    print(f"   Found: {modules}")

    # Load all modules
    print("\n2. Loading all modules...")
    all_modules = loader.load_all_modules()
    print(f"   Loaded {len(all_modules)} module(s):")
    for module_id, module in all_modules.items():
        print(f"   - {module.name} (v{module.version})")
        print(f"     Controls: {len(module.controls)}, Priority: {module.priority}")

    # Check active (should be none initially)
    print("\n3. Checking active modules...")
    active = loader.load_active_modules()
    print(f"   Active: {len(active)} module(s)")

    print("\n" + "=" * 70 + "\n")


def test_module_activation():
    """Test module activation."""
    print("=" * 70)
    print("TEST 2: Module Activation")
    print("=" * 70)

    loader = ComplianceLoader()

    # Activate HIPAA
    print("\n1. Activating HIPAA module...")
    success = loader.activate_module("hipaa-2024")
    print(f"   Success: {success}")

    # Load active
    print("\n2. Loading active modules...")
    active = loader.load_active_modules()
    print(f"   Active: {len(active)} module(s)")
    for module in active:
        print(f"   - {module.name}")

    # Deactivate
    print("\n3. Deactivating HIPAA module...")
    success = loader.deactivate_module("hipaa-2024")
    print(f"   Success: {success}")

    active = loader.load_active_modules()
    print(f"   Active after deactivation: {len(active)} module(s)")

    print("\n" + "=" * 70 + "\n")


def test_prompt_enhancement():
    """Test prompt enhancement with compliance context."""
    print("=" * 70)
    print("TEST 3: Prompt Enhancement")
    print("=" * 70)

    loader = ComplianceLoader()

    # Activate HIPAA
    loader.activate_module("hipaa-2024")
    active = loader.load_active_modules()

    # Base prompt
    base_prompt = """You are a backend developer.

Build a patient management API with the following endpoints:
- POST /api/patients (create patient record)
- GET /api/patients/:id (get patient details)
- PUT /api/patients/:id (update patient info)
- DELETE /api/patients/:id (delete patient record)

Include proper authentication and validation."""

    print("\n1. Base prompt:")
    print("-" * 70)
    print(base_prompt)

    # Enhanced prompt
    print("\n2. Enhanced prompt (with HIPAA):")
    print("-" * 70)
    enhanced = loader.enhance_prompt(base_prompt, active)
    print(enhanced)

    print("\n" + "=" * 70 + "\n")


def test_multi_module_layering():
    """Test layering multiple compliance modules."""
    print("=" * 70)
    print("TEST 4: Multi-Module Layering (HIPAA + SOC 2)")
    print("=" * 70)

    loader = ComplianceLoader()

    # Activate both modules
    print("\n1. Activating HIPAA (priority 100) and SOC 2 (priority 90)...")
    loader.activate_module("hipaa-2024")
    loader.activate_module("soc2")

    active = loader.load_active_modules()
    print(f"   Active: {len(active)} module(s)")
    for module in active:
        print(f"   - {module.name} (priority {module.priority})")

    # Get controls for file_write trigger
    print("\n2. Getting controls for 'file_write' trigger...")
    controls = loader.get_controls_for_trigger("file_write")
    print(f"   Found {len(controls)} control(s):")
    for module, control in controls:
        print(f"   - [{module.name}] {control.name}")
        print(f"     Enforcement: {control.enforcement_level.value}")
        print(f"     Rules: {len(control.rules)}")

    # Test prompt enhancement with both
    print("\n3. Enhanced prompt (with both modules):")
    print("-" * 70)
    base = "Build a secure healthcare API"
    enhanced = loader.enhance_prompt(base, active)
    print(enhanced)

    # Cleanup
    loader.deactivate_module("hipaa-2024")
    loader.deactivate_module("soc2")

    print("\n" + "=" * 70 + "\n")


def test_control_resolution():
    """Test control resolution and enforcement merging."""
    print("=" * 70)
    print("TEST 5: Control Resolution")
    print("=" * 70)

    loader = ComplianceLoader()

    # Activate both
    loader.activate_module("hipaa-2024")
    loader.activate_module("soc2")

    print("\n1. Testing enforcement level merging...")

    # Get controls for different triggers
    triggers = ["file_write", "api_call", "blackboard_post"]

    for trigger in triggers:
        controls = loader.get_controls_for_trigger(trigger)
        if controls:
            control_objs = [c for _, c in controls]
            merged_level = loader.merge_enforcement_levels(control_objs)
            print(f"\n   Trigger: {trigger}")
            print(f"   Controls: {len(controls)}")
            print(f"   Merged enforcement: {merged_level.value}")

            for module, control in controls:
                print(f"     - {control.control_id}: {control.enforcement_level.value}")

    # Cleanup
    loader.deactivate_module("hipaa-2024")
    loader.deactivate_module("soc2")

    print("\n" + "=" * 70 + "\n")


def test_health_check():
    """Test system health check."""
    print("=" * 70)
    print("TEST 6: Health Check")
    print("=" * 70)

    loader = ComplianceLoader()

    print("\n1. Running health check...")
    health = loader.health_check()

    print(f"   Healthy: {health['healthy']}")
    print(f"   Active modules: {health['active_modules']}")
    print(f"   Available modules: {health['available_modules']}")

    if health['errors']:
        print(f"   Errors: {health['errors']}")
    else:
        print("   Errors: None")

    if health['warnings']:
        print(f"   Warnings: {health['warnings']}")
    else:
        print("   Warnings: None")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    print("\n")
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  COMPLIANCE LOADER - FULL TEST SUITE".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)
    print("\n")

    # Run all tests
    test_basic_flow()
    test_module_activation()
    test_prompt_enhancement()
    test_multi_module_layering()
    test_control_resolution()
    test_health_check()

    print("\n")
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  ALL TESTS COMPLETE".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)
    print("\n")
