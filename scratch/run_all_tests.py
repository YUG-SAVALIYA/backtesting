import sys
from pathlib import Path

# Add src to sys.path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))
sys.path.insert(0, str(root_dir))

import tests.test_gap_up_modes as t_gap
import tests.test_trade_management as t_tm

def run_module_tests(module):
    print(f"\nRunning tests in {module.__name__}:")
    test_funcs = [name for name in dir(module) if name.startswith("test_")]
    passed = 0
    failed = 0
    for func_name in test_funcs:
        func = getattr(module, func_name)
        try:
            func()
            print(f"  [PASS] {func_name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {func_name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    return passed, failed

if __name__ == "__main__":
    p1, f1 = run_module_tests(t_gap)
    p2, f2 = run_module_tests(t_tm)
    print(f"\nSummary: Passed: {p1+p2}, Failed: {f1+f2}")
    if f1 + f2 > 0:
        sys.exit(1)
    else:
        sys.exit(0)
