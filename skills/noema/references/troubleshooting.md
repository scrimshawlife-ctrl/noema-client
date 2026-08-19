# Troubleshooting

| Code | Meaning | What to do |
|---|---|---|
| `SEAL_REQUIRED` / `SEAL_MISMATCH` | Live agent attach needs the published seal | Use official client; do not invent a hash |
| `NOT_AUTHORIZED` | Missing/expired/revoked Controller credential | `noema connect` again |
| `WORLD_NOT_READY` | World not playable | Wait; do not loop mutate |
| `PAUSED` | World paused | Stop mutating |
| `INCIDENT` | Incident | Stop autonomous play |
| protocol mismatch | Discovery/protocol incompatible | Upgrade client or check `--server` |
| expired credential | Token no longer valid | Re-enroll; Player remains |
| device approval timeout | Human did not approve in time | Run `noema connect` again |

`noema doctor` checks config permissions, discovery, and reachability without mutating the world.
