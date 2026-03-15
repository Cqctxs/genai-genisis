"use client"; 

import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, AsciiRenderer, Center } from "@react-three/drei";
import * as THREE from "three";

// 1. The Spinning Benchy Component
function SpinningBenchy() {
  const { scene } = useGLTF("/models/3DBenchy.gltf"); 
  const ref = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.z += delta * 1.5;
  });

  return (
    <group ref={ref} rotation={[-Math.PI / 2, 0, 0]}>
      <primitive object={scene} />
    </group>
  );
}

// 2. The Main Scene Component
export default function AsciiBenchyScene({ color = "white" }: { color?: string }) {
  return (
    <div style={{ width: "100%", height: "100%", backgroundColor: "transparent" }}>
      <Canvas camera={{ position: [0, 0, -80], fov: 40 }}>

        {/* Keep the WebGL background black. The AsciiRenderer needs to "see"
            black so it knows to map the background to an empty space. */}
        <color attach="background" args={["black"]} />

        <ambientLight intensity={1} />
        {/* FIX 2: Move the light to Z: -50 so it illuminates the side the camera sees */}
        <directionalLight position={[10, 10, -50]} intensity={3} />

        <Center>
          <SpinningBenchy />
        </Center>

        <AsciiRenderer
          fgColor={color}
          bgColor="transparent"
          characters=" .:-+*=%@#"
          // FIX 3: Set invert to true! This forces darkness = space, and light = #
          invert={true}
        />
      </Canvas>
    </div>
  );
}