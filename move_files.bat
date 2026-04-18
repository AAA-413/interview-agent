@echo off
echo Moving test files to tests directory...
move test_*.py tests\ 2>/dev/null
move tmp_*.py tests\ 2>/dev/null

echo Moving script files to scripts directory...
move check_users.py scripts\ 2>/dev/null
move run_user_migration.py scripts\ 2>/dev/null
move update_admin_password.py scripts\ 2>/dev/null
move verify_optimizations.py scripts\ 2>/dev/null

echo Done!
pause
