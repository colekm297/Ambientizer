import os
import numpy as np
from PIL import Image
from warp_engine import WarpEngine

def create_mock_assets(size=(512, 512)):
    h, w = size
    # Create a gradient image
    y, x = np.mgrid[0:h, 0:w]
    gradient = ((x / w) * 255).astype(np.uint8)
    image = np.stack([gradient, (255 - gradient), ((y / h) * 255).astype(np.uint8)], axis=-1)
    
    # Create a circular mask in the center
    center_y, center_x = h // 2, w // 2
    radius = min(h, w) // 3
    dist_sq = (y - center_y)**2 + (x - center_x)**2
    mask = (dist_sq < radius**2).astype(np.float32)
    
    # Create a simple U/V flow map (moving right and slightly down)
    u_flow = np.ones((h, w), dtype=np.float32) * 50.0
    v_flow = np.ones((h, w), dtype=np.float32) * 20.0
    
    return image, mask, u_flow, v_flow

def main():
    output_dir = "test_output"
    os.makedirs(output_dir, exist_ok=True)
    
    print("Generating mock assets...")
    img, mask, u, v = create_mock_assets()
    
    engine = WarpEngine()
    duration = 2.0  # seconds
    fps = 10
    total_frames = int(duration * fps)
    
    print(f"Running WarpEngine for {total_frames} frames...")
    for i in range(total_frames):
        t = i / fps
        # Warp the frame
        warped = engine.warp_frame(img, u, v, mask, t, duration)
        
        # Save output
        out_path = os.path.join(output_dir, f"frame_{i:03d}.png")
        Image.fromarray(warped).save(out_path)
        
        if i % 5 == 0:
            print(f"  Processed frame {i}/{total_frames}")

    print(f"\nSuccess! Test frames saved to the '{output_dir}' directory.")
    print("Verify the dual-phase loop by checking if the motion flows smoothly")
    print("and returns to the start state at the end of the sequence.")

if __name__ == "__main__":
    main()
