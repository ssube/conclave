#!/bin/bash
# Skill wrapper — delegates to the main agent-healthcheck script
exec bash /opt/conclave/scripts/agent-healthcheck.sh "$@"
