#!/usr/bin/env bash
# Lewa: 2x2 (8080/8081/8095/8070). Prawa: pełna kolumna observability.
# Tytułów paneli NIE ruszamy; kolorowe prefiksy są tylko w treści logów.

set -euo pipefail

# Przejdź do katalogu projektu (plik jest w scripts/)
cd "$(dirname "$0")/.."

# 1) Odpal backend + observability (idempotentnie)
make stack-start
(
  cd infra/docker/observability
  docker compose -f docker-compose.yml -p logops-obs up -d
)

# 2) Zbij starą sesję tmux (jeśli była)
tmux kill-session -t logops 2>/dev/null || true

# 3) Nowa sesja i pierwszy panel
tmux new-session -d -s logops -n stack 'bash'
LEFT_TOP_LEFT="$(tmux display-message -p -t logops:stack '#{pane_id}')"

# 4) Prawa kolumna (observability) – pełna wysokość (bez wymuszania szerokości)
RIGHT_OBS="$(tmux split-window -h -t "$LEFT_TOP_LEFT" -P -F "#{pane_id}")"

# 5) Z lewego robimy siatkę 2x2 (bez procentów)
BOTTOM_LEFT="$(tmux split-window -v -t "$LEFT_TOP_LEFT" -P -F "#{pane_id}")"     # lewy-dół
TOP_RIGHT_LEFT="$(tmux split-window -h -t "$LEFT_TOP_LEFT" -P -F "#{pane_id}")"  # lewy-góra-prawo
BOTTOM_RIGHT="$(tmux split-window -h -t "$BOTTOM_LEFT" -P -F "#{pane_id}")"      # lewy-dół-prawo

# 6) Delikatne podbicie obramowania i mysz
tmux set -g mouse on
tmux set -g pane-active-border-style "fg=colour45,bold"

# 7) Logi z kolorowymi prefiksami (tytułów paneli nie zmieniamy)
tmux send-keys -t "$LEFT_TOP_LEFT"  'stdbuf -oL tail -n +1 -F logs/ingest.out  | awk '\''BEGIN{c="\033[38;5;40m";r="\033[0m"}{print c"[8080]"r, $0}'\''' C-m  # 8080 (zielony)
tmux send-keys -t "$TOP_RIGHT_LEFT" 'stdbuf -oL tail -n +1 -F logs/authgw.out  | awk '\''BEGIN{c="\033[38;5;226m";r="\033[0m"}{print c"[8081]"r, $0}'\''' C-m # 8081 (żółty)
tmux send-keys -t "$BOTTOM_LEFT"    'stdbuf -oL tail -n +1 -F logs/core.out    | awk '\''BEGIN{c="\033[38;5;39m";r="\033[0m"}{print c"[8095]"r, $0}'\''' C-m  # 8095 (niebieski)
tmux send-keys -t "$BOTTOM_RIGHT"   'stdbuf -oL tail -n +1 -F logs/orch.out    | awk '\''BEGIN{c="\033[38;5;205m";r="\033[0m"}{print c"[8070]"r, $0}'\''' C-m # 8070 (magenta)

# 8) Observability (prawa kolumna) + prefiks [OBS] (cyjan)
tmux send-keys -t "$RIGHT_OBS" 'cd infra/docker/observability && docker compose -f docker-compose.yml -p logops-obs logs -f | awk '\''BEGIN{c="\033[38;5;51m";r="\033[0m"}{print c"[OBS]"r, $0}'\''' C-m

# 9) Wejście do sesji
tmux attach -t logops
