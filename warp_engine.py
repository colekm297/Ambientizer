import numpy as np
from scipy.ndimage import map_coordinates

class WarpEngine:
    \"\"\"
    WarpEngine implements dual-phase vector warping for seamless looping motion.
    
    This technique uses two phase-shifted displacement fields that are blended
    using a sine-wave cross-fade to ensure that the motion loops perfectly
    without visible jumps or resets.
    \"\"\"
    
    def __init__(self, size: tuple[int, int]):
        \"\"\"
        Initialize the WarpEngine with the target image size (height, width).
        \"\"\"
        self.height, self.width = size
        self.y_grid, self.x_grid = np.mgrid[0:self.height, 0:self.width]

    def warp_frame(self, 
                   image: np.ndarray, 
                   u_flow: np.ndarray, 
                   v_flow: np.ndarray, 
                   mask: np.ndarray, 
                   t: float, 
                   loop_period: float = 1.0,
                   intensity: float = 1.0) -> np.ndarray:
        \"\"\"
        Generate a single warped frame at time t.
        
        Args:
            image: Input image as a numpy array (H, W, C).
            u_flow: Horizontal flow field (H, W).
            v_flow: Vertical flow field (H, W).
            mask: Motion mask (H, W), 0 to 1.
            t: Current time in seconds.
            loop_period: Total duration of the loop in seconds.
            intensity: Overall motion multiplier.
            
        Returns:
            Warped image as a numpy array.
        \"\"\"
        # Normalize time to [0, 1]
        phase0 = (t / loop_period) % 1.0
        phase1 = (phase0 + 0.5) % 1.0
        
        # Calculate weights for cross-fading (sine-based for smoothness)
        # weight goes from 0 to 1 and back to 0
        w1 = 0.5 - 0.5 * np.cos(2 * np.pi * phase0)
        w0 = 1.0 - w1
        
        # Apply the mask to the flow fields
        u_effective = u_flow * mask * intensity
        v_effective = v_flow * mask * intensity
        
        # Compute coordinates for phase 0
        coords0 = np.array([
            self.y_grid - v_effective * phase0,
            self.x_grid - u_effective * phase0
        ])
        
        # Compute coordinates for phase 1
        coords1 = np.array([
            self.y_grid - v_effective * phase1,
            self.x_grid - u_effective * phase1
        ])
        
        # Perform the warps for each color channel
        warped0 = np.zeros_like(image, dtype=np.float32)
        warped1 = np.zeros_like(image, dtype=np.float32)
        
        for c in range(image.shape[2]):
            warped0[..., c] = map_coordinates(image[..., c], coords0, order=1, mode='reflect')
            warped1[..., c] = map_coordinates(image[..., c], coords1, order=1, mode='reflect')
            
        # Blend the two phases
        result = (warped0 * w0 + warped1 * w1).astype(np.uint8)
        
        return result

    def generate_loop(self, 
                      image: np.ndarray, 
                      u_flow: np.ndarray, 
                      v_flow: np.ndarray, 
                      mask: np.ndarray, 
                      loop_period: float = 2.0, 
                      fps: int = 30,
                      intensity: float = 1.0) -> list[np.ndarray]:
        \"\"\"
        Generate a full sequence of frames for a seamless loop.
        \"\"\"
        num_frames = int(loop_period * fps)
        frames = []
        
        for i in range(num_frames):
            t = i / fps
            frame = self.warp_frame(image, u_flow, v_flow, mask, t, loop_period, intensity)
            frames.append(frame)
            
        return frames
