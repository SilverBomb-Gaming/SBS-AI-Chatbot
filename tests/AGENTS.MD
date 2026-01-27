# AGENTS.md — SBS-AI-Chatbot

## Project
Vision-based reinforcement learning trainer for Street Fighter 6.
The agent controls Player 2 via a virtual gamepad while Player 1 is human-controlled.

## Current State (DO NOT REFACTOR)
- Window capture, DPI awareness, and client rect alignment are correct.
- Trainer loop, reward pipeline, and action dispatch are functional.
- Debug HUD frames are always written when --debug-hud is enabled.
- Virtual controller input is used for the agent.
- Player 1 should be controlled by a physical gamepad (Xbox controller).

## HUD / Vision
- Street Fighter 6 HP bars are parallelogram-shaped.
- Polygon-based ROIs are used instead of rectangles.
- Polygon alignment is not final and must be manually tuned using debug screenshots.
- Perfect pixel alignment is NOT required; monotonic HP decrease is sufficient.
- Do not introduce auto-calibration or heuristics unless explicitly requested.

## Control Requirements
- Virtual controller must remain persistent across episodes.
- Agent must only send inputs to Player 2.
- Player 1 is human-controlled and should never be overridden.

## What to Work On Next
1. Persistent virtual controller stability (Player 2 assignment).
2. Final polygon HUD alignment using known-good reference screenshots.
3. Resume training once HUD readings are stable.

## What NOT to Do
- Do not switch back to rectangular HUD ROIs.
- Do not refactor capture math or DPI logic.
- Do not remove debug artifact generation.
- Do not introduce keyboard/mouse dependencies.

## Notes
Untracked local scripts (intentionally excluded):
- vgamepad_test.py
- vgamepad_persistent_test.py
- spam_right_10s.py
- policies/
