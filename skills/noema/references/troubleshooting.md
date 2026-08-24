# Troubleshooting

| Code | Meaning | What to do |
|---|---|---|
| `SEAL_REQUIRED` / `SEAL_MISMATCH` | Live agent attach needs the published seal | Use official client; do not invent a hash |
| `NOT_AUTHORIZED` | Missing/expired/revoked Controller credential | `noema connect` (re-enrolls when the stored JWT is expired/invalid). Use `--force` if a still-unexpired token is rejected. |
| `WORLD_NOT_READY` | World not playable | Wait; do not loop mutate |
| `PAUSED` | World paused | Stop mutating |
| `INCIDENT` | Incident | Stop autonomous play |
| `SETTLEMENT_RESYNC` | World head resynced; command not applied | Client retries **once** with the same keys; if it fails again, stop. Not INCIDENT |
| protocol mismatch | Discovery/protocol incompatible | Upgrade client or check `--server` |
| expired credential | Local JWT `exp` has passed | `noema status` / `doctor` report `credential: expired`; `noema connect` starts device enrollment. Player remains |
| device approval timeout | Human did not approve in time | Run `noema connect` again |

`noema doctor` checks config permissions, discovery, local credential expiry, and `/health` reachability without mutating the world. It does not treat a stored-but-expired JWT as connected.
