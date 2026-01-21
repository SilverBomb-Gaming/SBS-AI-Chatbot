using UnityEngine;

/// <summary>
/// Extremely small WASD controller so we always have visible movement in the harness scene.
/// Hold right mouse to rotate the capsule; movement is top-down relative to facing.
/// </summary>
[RequireComponent(typeof(CharacterController))]
public class SimplePlayerController : MonoBehaviour
{
    [SerializeField]
    private float moveSpeed = 3f;

    [SerializeField]
    private float lookSpeed = 140f;

    [SerializeField]
    private Transform followCamera;

    private CharacterController _characterController;
    private float _yaw;

    private void Awake()
    {
        _characterController = GetComponent<CharacterController>();
        _yaw = transform.eulerAngles.y;
    }

    private void Update()
    {
        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");

        Vector3 input = new Vector3(h, 0f, v);
        input = Vector3.ClampMagnitude(input, 1f);
        Vector3 velocity = transform.TransformDirection(input) * moveSpeed;
        _characterController.SimpleMove(velocity);

        if (Input.GetMouseButton(1))
        {
            _yaw += Input.GetAxis("Mouse X") * lookSpeed * Time.deltaTime;
            transform.rotation = Quaternion.Euler(0f, _yaw, 0f);
        }

        if (followCamera)
        {
            Vector3 target = transform.position + transform.forward * 0.5f + Vector3.up * 1.6f;
            followCamera.position = transform.position + Vector3.up * 1.7f - transform.forward * 2.4f;
            followCamera.LookAt(target, Vector3.up);
        }
    }

    public void AttachCamera(Transform cameraTransform)
    {
        followCamera = cameraTransform;
        _yaw = transform.eulerAngles.y;
    }
}
