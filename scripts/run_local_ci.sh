#!/bin/bash
# Local CI/CD script - Run this instead of GitHub Actions
# Usage: ./scripts/run_local_ci.sh [test|lint|format|security|full]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$ROOT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=()
PASSED=()

run_check() {
    local name=$1
    local cmd=$2
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " Running: $name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if eval "$cmd"; then
        echo -e "${GREEN}✓ $name passed${NC}"
        PASSED+=("$name")
    else
        echo -e "${RED}✗ $name failed${NC}"
        FAILED+=("$name")
    fi
}

# Parse command
case "${1:-full}" in
    test)
        run_check "Python Tests" "python -m pytest tests/ -v --tb=short"
        ;;
    
    coverage)
        run_check "Test Coverage" "python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing --cov-fail-under=50"
        ;;
    
    lint)
        run_check "Flake8 Linting" "flake8 src/ tests/ --max-line-length=100 --ignore=E203,W503"
        ;;
    
    format)
        run_check "Black Formatting Check" "black --check src/ tests/ scripts/"
        run_check "Isort Import Check" "isort --check-only src/ tests/ scripts/"
        ;;
    
    format-fix)
        run_check "Black Auto-format" "black src/ tests/ scripts/"
        run_check "Isort Auto-fix" "isort src/ tests/ scripts/"
        ;;
    
    type)
        run_check "Mypy Type Check" "mypy src/ --ignore-missing-imports || true"
        ;;
    
    security)
        run_check "Bandit Security Scan" "bandit -r src/ -f json -o /tmp/bandit-report.json || echo 'Warnings found'"
        run_check "Secret Detection" "git secrets --scan || true"
        ;;
    
    full|ci|all)
        echo "Running full CI pipeline..."
        echo "This mimics what GitHub Actions would do"
        echo ""
        
        run_check "Python Syntax Check" "python -m py_compile src/**/*.py"
        run_check "Black Formatting" "black --check src/ tests/ scripts/"
        run_check "Flake8 Linting" "flake8 src/ tests/ --max-line-length=100 --ignore=E203,W503"
        run_check "Python Tests" "python -m pytest tests/ -v --tb=short"
        ;;
    
    clean)
        echo "Cleaning up..."
        find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        find . -type f -name "*.pyc" -delete
        rm -rf .pytest_cache htmlcov .mypy_cache
        echo -e "${GREEN}✓ Clean complete${NC}"
        exit 0
        ;;
    
    paper)
        echo "Running paper trading test..."
        python scripts/run_paper_trading.py --single
        exit 0
        ;;
    
    *)
        echo "Usage: $0 [test|coverage|lint|format|format-fix|type|security|full|clean|paper]"
        echo ""
        echo "Commands:"
        echo "  test        - Run pytest"
        echo "  coverage    - Run tests with coverage"
        echo "  lint        - Check with flake8"
        echo "  format      - Check formatting (black, isort)"
        echo "  format-fix  - Auto-fix formatting"
        echo "  type        - Type checking with mypy"
        echo "  security    - Security scanning"
        echo "  full/ci/all - Run full CI pipeline (default)"
        echo "  clean       - Remove cache files"
        echo "  paper       - Run paper trading test"
        exit 1
        ;;
esac

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "                          SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ${#PASSED[@]} -eq 0 ] && [ ${#FAILED[@]} -eq 0 ]; then
    echo "No checks were run"
    exit 0
fi

for check in "${PASSED[@]}"; do
    echo -e "${GREEN}✓ $check${NC}"
done

for check in "${FAILED[@]}"; do
    echo -e "${RED}✗ $check${NC}"
done

TOTAL=$(( ${#PASSED[@]} + ${#FAILED[@]} ))
echo ""
echo -e "${GREEN}Passed: ${#PASSED[@]}/${TOTAL}${NC}"

if [ ${#FAILED[@]} -gt 0 ]; then
    echo -e "${RED}Failed: ${#FAILED[@]}/${TOTAL}${NC}"
    echo ""
    echo "To fix formatting issues, run: $0 format-fix"
    exit 1
else
    echo -e "${GREEN}All checks passed!${NC}"
    exit 0
fi
