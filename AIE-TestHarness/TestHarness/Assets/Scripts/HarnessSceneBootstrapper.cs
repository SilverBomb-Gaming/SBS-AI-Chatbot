using UnityEngine;

/// <summary>
/// Guarantees the test harness scene always contains the geometry, light, camera, and player objects.
/// This prevents manual scene editing and keeps the build deterministic.
/// </summary>
[DefaultExecutionOrder(-200)]
public class HarnessSceneBootstrapper : MonoBehaviour
{
    [SerializeField]
    private Color floorColor = new Color(0.2f, 0.25f, 0.32f);

    [SerializeField]
    private float cubeSpread = 3f;

    [SerializeField]
    private Vector3[] cubeOffsets =
    {
        new Vector3(-2.5f, 0.5f, 3f),
        new Vector3(2.5f, 0.5f, 2f),
        new Vector3(1.5f, 0.5f, -2.5f)
    };

    private void Awake()
    {
        Camera mainCamera = EnsureCamera();
        EnsureLight();
        EnsureFloor();
        EnsureCubes();
        GameObject player = EnsurePlayer();

        if (mainCamera && player)
        {
            var controller = player.GetComponent<SimplePlayerController>();
            controller?.AttachCamera(mainCamera.transform);
        }
    }

    private Camera EnsureCamera()
    {
        Camera existing = Camera.main;
        if (existing)
        {
            existing.transform.position = new Vector3(0f, 2.5f, -6f);
            existing.transform.LookAt(Vector3.zero + Vector3.up * 0.5f);
            return existing;
        }

        GameObject cameraGo = new GameObject("Main Camera");
        cameraGo.tag = "MainCamera";
        var camera = cameraGo.AddComponent<Camera>();
        cameraGo.AddComponent<AudioListener>();
        camera.transform.position = new Vector3(0f, 2.5f, -6f);
        camera.transform.LookAt(Vector3.zero + Vector3.up * 0.5f);
        camera.nearClipPlane = 0.1f;
        camera.farClipPlane = 100f;
        return camera;
    }

    private void EnsureLight()
    {
        Light existing = FindObjectOfType<Light>();
        if (existing)
        {
            existing.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            existing.intensity = 1.2f;
            existing.color = Color.white;
            return;
        }

        GameObject lightGo = new GameObject("Directional Light");
        var light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.color = Color.white;
        light.intensity = 1.2f;
        light.shadows = LightShadows.Soft;
        lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
    }

    private void EnsureFloor()
    {
        GameObject floor = GameObject.Find("Floor");
        if (!floor)
        {
            floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.localScale = new Vector3(4f, 1f, 4f);
            floor.transform.position = Vector3.zero;
        }

        var renderer = floor.GetComponent<Renderer>();
        if (renderer)
        {
            Material material = renderer.sharedMaterial;
            if (!material || material.name == "Default-Material")
            {
                material = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard"));
                renderer.sharedMaterial = material;
            }

            renderer.sharedMaterial.color = floorColor;
        }
    }

    private void EnsureCubes()
    {
        for (int i = 0; i < cubeOffsets.Length; i++)
        {
            string cubeName = $"Cube_{i + 1}";
            GameObject cube = GameObject.Find(cubeName);
            if (!cube)
            {
                cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
                cube.name = cubeName;
                cube.transform.localScale = new Vector3(1f, 1f, 1f);
            }

            cube.transform.position = cubeOffsets[i];
            var renderer = cube.GetComponent<Renderer>();
            if (renderer)
            {
                renderer.sharedMaterial.color = Color.HSVToRGB(0.1f * i, 0.6f, 0.9f);
            }
        }
    }

    private GameObject EnsurePlayer()
    {
        GameObject player = GameObject.Find("PlayerCapsule");
        if (!player)
        {
            player = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            player.name = "PlayerCapsule";
        }

        player.transform.position = new Vector3(0f, 1f, 0f);
        player.transform.rotation = Quaternion.identity;

        Collider collider = player.GetComponent<Collider>();
        if (collider)
        {
            Destroy(collider);
        }

        var controller = player.GetComponent<CharacterController>();
        if (!controller)
        {
            controller = player.AddComponent<CharacterController>();
            controller.height = 2f;
            controller.radius = 0.45f;
        }

        if (!player.TryGetComponent(out SimplePlayerController playerController))
        {
            playerController = player.AddComponent<SimplePlayerController>();
        }

        return player;
    }
}
