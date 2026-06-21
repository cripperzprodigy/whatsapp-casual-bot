#!/bin/bash
# install_deps.sh - Smart Pre-Flight Dependency Checker and Installer

set -e

# --- Color Codes ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Privilege Check ---
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}⚠️  This script requires elevated privileges to install system packages.${NC}"
    echo -e "${YELLOW}Attempting to elevate with sudo...${NC}"
    exec sudo bash "$0" "$@"
fi

# --- Variables ---
MISSING_PKGS=()
OS_VERSION=""
OS_NAME=""

# --- OS Detection ---
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME=$ID
        OS_VERSION=$VERSION_ID
        echo -e "${GREEN}Detected OS: $OS_NAME $OS_VERSION${NC}"
    else
        echo -e "${RED}❌ Could not detect OS version. Assuming Ubuntu/Debian.${NC}"
        OS_NAME="ubuntu"
        OS_VERSION="unknown"
    fi
}

# --- Base Update ---
update_apt() {
    echo -e "\n⏳ Updating apt repositories..."
    if ! apt-get update -y; then
        echo -e "${YELLOW}⚠️  Standard apt update failed. Checking for EOL repositories...${NC}"
        # Fallback for old releases
        sed -i -re 's/([a-z]{2}\.)?archive.ubuntu.com|security.ubuntu.com/old-releases.ubuntu.com/g' /etc/apt/sources.list
        if ! apt-get update -y; then
            echo -e "${RED}❌ Critical: Unable to update apt repositories even with old-releases.${NC}"
            exit 0
        fi
    fi
}

# --- Install Package with Fallback ---
install_pkg() {
    local pkg=$1
    echo -e "⏳ Installing ${pkg}..."
    if apt-get install -y "$pkg" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ ${pkg} installed successfully via apt.${NC}"
        return 0
    else
        echo -e "${RED}❌ Failed to install ${pkg} via apt.${NC}"
        return 1
    fi
}

# --- SQLite3 Smart Install ---
install_sqlite() {
    echo -e "\n⏳ Attempting to install SQLite3 and headers..."
    if install_pkg "libsqlite3-dev" && install_pkg "sqlite3"; then
        return 0
    else
        echo -e "${YELLOW}⚠️  Apt failed for SQLite. Attempting manual compile fallback...${NC}"
        local SQLITE_YEAR="2023"
        local SQLITE_VERSION="3440200" # Example version 3.44.2
        local SQLITE_URL="https://www.sqlite.org/${SQLITE_YEAR}/sqlite-autoconf-${SQLITE_VERSION}.tar.gz"

        local TEMP_DIR=$(mktemp -d)
        cd "$TEMP_DIR"

        if wget -q --show-progress "$SQLITE_URL"; then
            tar -xzf "sqlite-autoconf-${SQLITE_VERSION}.tar.gz"
            cd "sqlite-autoconf-${SQLITE_VERSION}"
            ./configure >/dev/null
            make -j $(nproc) >/dev/null
            make install >/dev/null
            ldconfig
            echo -e "${GREEN}✅ SQLite compiled and installed from source.${NC}"
            cd - >/dev/null
            rm -rf "$TEMP_DIR"
            return 0
        else
            echo -e "${RED}❌ Critical: Could not download SQLite source. Manual compilation failed.${NC}"
            cd - >/dev/null
            rm -rf "$TEMP_DIR"
            MISSING_PKGS+=("libsqlite3-dev")
            return 1
        fi
    fi
}

# --- Python 3.12 Smart Install ---
install_python312() {
    echo -e "\n⏳ Attempting to install Python 3.12..."

    # Check if we need deadsnakes PPA (Ubuntu < 23.10)
    if [[ "$OS_NAME" == "ubuntu" ]]; then
        # Use simple string comparison for version
        if [[ "$OS_VERSION" < "23.10" ]]; then
            echo -e "${YELLOW}⚠️  Ubuntu version < 23.10 detected. Adding deadsnakes PPA...${NC}"
            install_pkg "software-properties-common"
            add-apt-repository ppa:deadsnakes/ppa -y || true
            apt-get update -y >/dev/null
        fi
    fi

    local PY_PKGS=("python3.12" "python3.12-venv" "python3.12-dev")
    local success=true

    for pkg in "${PY_PKGS[@]}"; do
        if ! install_pkg "$pkg"; then
            MISSING_PKGS+=("$pkg")
            success=false
        fi
    done

    if [ "$success" = true ]; then
        return 0
    else
        echo -e "${RED}❌ Failed to install Python 3.12 packages via apt.${NC}"
        return 1
    fi
}

# --- Verification ---
verify_installation() {
    echo -e "\n⏳ Verifying Python and SQLite linkage..."
    if ! command -v python3.12 &> /dev/null; then
        echo -e "${RED}❌ Critical: python3.12 is not in PATH after installation.${NC}"
        return 1
    fi

    if python3.12 -c "import sqlite3; print('SQLite OK')" &> /dev/null; then
        echo -e "${GREEN}✅ Verification successful: Python 3.12 loads sqlite3.${NC}"
        return 0
    else
        echo -e "${RED}❌ Critical: python3.12 cannot import sqlite3. Python was likely built without libsqlite3-dev.${NC}"
        # We don't want to break the script completely, but we mark it as missing
        MISSING_PKGS+=("python3.12-sqlite3-linkage")
        return 1
    fi
}

# --- Main Execution Flow ---
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Pre-Flight Dependency Installer        ${NC}"
echo -e "${GREEN}=========================================${NC}"

detect_os
update_apt

echo -e "\n⏳ Installing base dependencies..."
for pkg in "build-essential" "git" "curl" "wget"; do
    if ! install_pkg "$pkg"; then
        MISSING_PKGS+=("$pkg")
    fi
done

install_sqlite
install_python312

# Skip verification if python3.12 itself failed to install via apt
if command -v python3.12 &> /dev/null; then
    verify_installation
fi

# --- Summary ---
echo -e "\n========================================="
if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ All dependencies installed successfully!${NC}"
    exit 1
else
    echo -e "${RED}❌ Missing or failed dependencies:${NC}"
    for missing in "${MISSING_PKGS[@]}"; do
        echo -e "   - $missing"
    done
    kill -INT $$
fi
