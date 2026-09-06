#!/usr/bin/env bash
# Run Recall against the demo space instead of the user's live person graph.
#
#   ./demo_space.sh                 # web UI on the demo space
#   ./demo_space.sh reset           # empty the demo space, keep using it
#   ./demo_space.sh seed            # add the confusable cast (needed for EIG)
#   ./demo_space.sh <anything else> # any uv command, pointed at the demo space
#
# The live graph at data/person_graph.json is never touched by anything here.
set -euo pipefail
cd "$(dirname "$0")"

SPACE=data/demo_space
export RECALL_STORE_PATH="$SPACE/graph.json"
export RECALL_RELATIONS_PATH="$SPACE/relations.json"
export RECALL_CALENDAR_PATH="$SPACE/calendar.json"
export RECALL_ICS_DIR="$SPACE/ics"

case "${1:-}" in
  reset)
    echo '{"people": []}'    > "$RECALL_STORE_PATH"
    echo '{"relations": []}' > "$RECALL_RELATIONS_PATH"
    echo '{"events": []}'    > "$RECALL_CALENDAR_PATH"
    rm -f "$RECALL_ICS_DIR"/*.ics
    echo "demo space emptied: $SPACE"
    ;;
  seed)
    shift
    uv run seed_demo.py --store "$RECALL_STORE_PATH" "$@"
    ;;
  "")
    echo "store: $RECALL_STORE_PATH"
    uv run web/server.py
    ;;
  *)
    uv run "$@"
    ;;
esac
