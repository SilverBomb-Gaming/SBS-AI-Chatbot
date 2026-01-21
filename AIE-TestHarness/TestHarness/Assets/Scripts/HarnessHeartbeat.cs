using System;
using System.Collections;
using UnityEngine;

/// <summary>
/// Emits deterministic heartbeat logs so the runner can validate ingestion without Babylon.
/// </summary>
public class HarnessHeartbeat : MonoBehaviour
{
    [Tooltip("Seconds between heartbeat log entries.")]
    public float heartbeatIntervalSeconds = 2f;

    [Tooltip("Auto-quit after this many seconds (set 0 or negative to disable).")]
    public float autoQuitAfterSeconds = 45f;

    private float _startRealtime;
    private float _nextHeartbeat;
    private int _frameCount;
    private bool _quitRequested;

    private void Start()
    {
        _startRealtime = Time.realtimeSinceStartup;
        _nextHeartbeat = _startRealtime + Mathf.Max(0.1f, heartbeatIntervalSeconds);
        DateTimeOffset utcNow = DateTimeOffset.UtcNow;
        Debug.Log($"[HarnessHeartbeat] start_time={utcNow:o}");
    }

    private void Update()
    {
        _frameCount++;
        float elapsed = Time.realtimeSinceStartup - _startRealtime;

        if (Time.realtimeSinceStartup >= _nextHeartbeat)
        {
            float fps = Mathf.Approximately(elapsed, 0f) ? 0f : _frameCount / elapsed;
            Debug.Log($"[HarnessHeartbeat] t={elapsed:F1}s frames={_frameCount} fps={fps:F1}");
            _nextHeartbeat += Mathf.Max(0.1f, heartbeatIntervalSeconds);
        }

        if (!_quitRequested && autoQuitAfterSeconds > 0f && elapsed >= autoQuitAfterSeconds)
        {
            _quitRequested = true;
            Debug.Log($"[HarnessHeartbeat] auto-quit after {elapsed:F1}s");
            StartCoroutine(QuitAfterFrame());
        }
    }

    private IEnumerator QuitAfterFrame()
    {
        yield return null;
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#else
        Application.Quit(0);
#endif
    }

    private void OnApplicationQuit()
    {
        float elapsed = Time.realtimeSinceStartup - _startRealtime;
        float fps = Mathf.Approximately(elapsed, 0f) ? 0f : _frameCount / elapsed;
        Debug.Log($"[HarnessHeartbeat] quitting after {elapsed:F1}s frames={_frameCount} fps={fps:F1}");
    }
}
