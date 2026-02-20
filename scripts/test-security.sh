#!/bin/bash
# Test script for security hardening.
# Runs the ansible playbook, then startup.sh (setup-only mode),
# then validates all security hardening changes.
#
# Usage: sudo bash scripts/test-security.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_DIR/.venv"
WORKSPACE="/workspace"

PASS=0
FAIL=0

pass() { echo "  PASS: $1"; ((PASS++)); }
fail() { echo "  FAIL: $1"; ((FAIL++)); }

# ---------------------------------------------------------------
# 0. Run ansible playbook
# ---------------------------------------------------------------
echo "=== Step 1: Running ansible playbook ==="
"$VENV/bin/ansible-playbook" \
  -i "$REPO_DIR/ansible/inventory.yml" \
  "$REPO_DIR/ansible/playbook.yml"
echo ""

# ---------------------------------------------------------------
# 1. Run startup.sh in setup-only mode
# ---------------------------------------------------------------
echo "=== Step 2: Running startup.sh (setup-only) ==="

# Ensure secrets file exists so startup.sh can source it
if [ ! -f "$WORKSPACE/config/generated-secrets.env" ]; then
    mkdir -p "$WORKSPACE/config"
    cat > "$WORKSPACE/config/generated-secrets.env" <<SECRETS_EOF
SYNAPSE_DB_PASSWORD=$(openssl rand -hex 32)
PLANKA_DB_PASSWORD=$(openssl rand -hex 32)
PLANKA_SECRET_KEY=$(openssl rand -hex 32)
CHROMADB_TOKEN=$(openssl rand -hex 32)
SYNAPSE_REGISTRATION_SHARED_SECRET=$(openssl rand -hex 32)
SYNAPSE_MACAROON_SECRET_KEY=$(openssl rand -hex 32)
SYNAPSE_FORM_SECRET=$(openssl rand -hex 32)
SECRETS_EOF
    chmod 600 "$WORKSPACE/config/generated-secrets.env"
fi

# Mark initialized to skip first-boot postgres/synapse init
# (this test validates security hardening, not service initialization)
touch "$WORKSPACE/.initialized"

CONCLAVE_SETUP_ONLY=1 \
NGINX_PASSWORD=testpass \
SSH_AUTHORIZED_KEYS="ssh-ed25519 AAAA_test_key testuser@test" \
  bash "$SCRIPT_DIR/startup.sh"
echo ""

# ---------------------------------------------------------------
# 2. Tests
# ---------------------------------------------------------------
echo "=== Step 3: Running tests ==="

# --- Dev user ---
echo ""
echo "--- Dev user ---"

if id dev &>/dev/null; then
    pass "dev user exists"
else
    fail "dev user does not exist"
fi

if id -nG dev 2>/dev/null | grep -qw sudo; then
    pass "dev user is in sudo group"
else
    fail "dev user is NOT in sudo group"
fi

DEV_HOME=$(getent passwd dev | cut -d: -f6)
if [ "$DEV_HOME" = "/workspace/data/coding" ]; then
    pass "dev home is /workspace/data/coding"
else
    fail "dev home is '$DEV_HOME', expected /workspace/data/coding"
fi

DEV_SHELL=$(getent passwd dev | cut -d: -f7)
if [ "$DEV_SHELL" = "/bin/bash" ]; then
    pass "dev shell is /bin/bash"
else
    fail "dev shell is '$DEV_SHELL', expected /bin/bash"
fi

if su -s /bin/sh dev -c "whoami" 2>/dev/null | grep -q dev; then
    pass "su - dev works, whoami returns dev"
else
    fail "su - dev -c whoami did not return dev"
fi

# --- SSH hardening ---
echo ""
echo "--- SSH hardening ---"

check_sshd_setting() {
    local setting="$1"
    local expected="$2"
    local label="$3"
    if grep -qE "^${setting}\s+${expected}" /etc/ssh/sshd_config; then
        pass "$label = $expected"
    else
        fail "$label: expected '$expected', not found in sshd_config"
    fi
}

check_sshd_setting "PasswordAuthentication" "no" "PasswordAuthentication"
check_sshd_setting "PermitRootLogin" "no" "PermitRootLogin"
check_sshd_setting "X11Forwarding" "no" "X11Forwarding"
check_sshd_setting "AllowAgentForwarding" "no" "AllowAgentForwarding"
check_sshd_setting "PubkeyAuthentication" "yes" "PubkeyAuthentication"
check_sshd_setting "MaxAuthTries" "3" "MaxAuthTries"
check_sshd_setting "LoginGraceTime" "30" "LoginGraceTime"

if sshd -t 2>/dev/null; then
    pass "sshd -t config validation passes"
else
    fail "sshd -t config validation failed"
fi

# --- fail2ban ---
echo ""
echo "--- fail2ban ---"

if dpkg -l fail2ban 2>/dev/null | grep -q '^ii'; then
    pass "fail2ban package is installed"
else
    fail "fail2ban package is NOT installed"
fi

if [ -f /etc/fail2ban/jail.d/sshd.conf ]; then
    pass "sshd jail config exists"
    if grep -q "enabled = true" /etc/fail2ban/jail.d/sshd.conf; then
        pass "sshd jail is enabled"
    else
        fail "sshd jail is NOT enabled"
    fi
else
    fail "sshd jail config does not exist"
fi

if [ -f /etc/fail2ban/jail.d/nginx-http-auth.conf ]; then
    pass "nginx-http-auth jail config exists"
    if grep -q "enabled = true" /etc/fail2ban/jail.d/nginx-http-auth.conf; then
        pass "nginx-http-auth jail is enabled"
    else
        fail "nginx-http-auth jail is NOT enabled"
    fi
else
    fail "nginx-http-auth jail config does not exist"
fi

# fail2ban-client status only works if fail2ban service is running
if systemctl is-active fail2ban &>/dev/null || pgrep -x fail2ban-server &>/dev/null; then
    if fail2ban-client status 2>/dev/null | grep -q "Jail list"; then
        pass "fail2ban-client status reports jails"
    else
        fail "fail2ban-client status did not report jails"
    fi
else
    echo "  SKIP: fail2ban service not running (jails configured but not started)"
fi

# --- Directory ownership ---
echo ""
echo "--- Directory ownership ---"

CODING_OWNER=$(stat -c '%U' "$WORKSPACE/data/coding")
if [ "$CODING_OWNER" = "dev" ]; then
    pass "/workspace/data/coding owned by dev"
else
    fail "/workspace/data/coding owned by '$CODING_OWNER', expected dev"
fi

PROJECTS_OWNER=$(stat -c '%U' "$WORKSPACE/data/coding/projects")
if [ "$PROJECTS_OWNER" = "dev" ]; then
    pass "/workspace/data/coding/projects owned by dev"
else
    fail "/workspace/data/coding/projects owned by '$PROJECTS_OWNER', expected dev"
fi

if su -s /bin/sh dev -c "touch $WORKSPACE/data/coding/projects/.write-test && rm $WORKSPACE/data/coding/projects/.write-test" 2>/dev/null; then
    pass "dev can write to /workspace/data/coding/projects"
else
    fail "dev CANNOT write to /workspace/data/coding/projects"
fi

SSH_DIR="$WORKSPACE/data/coding/.ssh"
if [ -d "$SSH_DIR" ]; then
    SSH_PERMS=$(stat -c '%a' "$SSH_DIR")
    SSH_OWNER=$(stat -c '%U' "$SSH_DIR")
    if [ "$SSH_PERMS" = "700" ] && [ "$SSH_OWNER" = "dev" ]; then
        pass ".ssh dir permissions 700, owned by dev"
    else
        fail ".ssh dir perms=$SSH_PERMS owner=$SSH_OWNER (expected 700/dev)"
    fi
else
    fail ".ssh directory does not exist"
fi

# --- supervisord.conf ---
echo ""
echo "--- supervisord.conf ---"

CONF="$REPO_DIR/configs/supervisord.conf"
if grep -A3 '^\[program:ttyd\]' "$CONF" | grep -q 'user=dev'; then
    pass "ttyd block has user=dev"
else
    fail "ttyd block does NOT have user=dev"
fi

if grep -A5 '^\[program:ttyd\]' "$CONF" | grep -q 'HOME="/workspace/data/coding"'; then
    pass "ttyd HOME is /workspace/data/coding"
else
    fail "ttyd HOME is not /workspace/data/coding"
fi

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
echo ""
echo "==============================="
echo "Results: $PASS passed, $FAIL failed"
echo "==============================="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
