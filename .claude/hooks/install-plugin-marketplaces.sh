#!/bin/bash
set -euo pipefail

# Remote sessions are fresh ephemeral containers: registering a marketplace in
# .claude/settings.json (extraKnownMarketplaces) never auto-installs its
# plugins, so each new remote session needs this to actually get the skills.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

claude plugin marketplace add obra/superpowers
claude plugin marketplace add mattpocock/skills
claude plugin marketplace add michael-denyer/pstack-claude

claude plugin install -y superpowers@superpowers-dev
claude plugin install -y mattpocock-skills@mattpocock
claude plugin install -y pstack@pstack-claude
