"use client";

import dynamic from "next/dynamic";

const DitherMapCanvas = dynamic(() => import("./dither-map-canvas"), {
  ssr: false,
  loading: () => <div className="absolute inset-0" />,
});

interface DitherMapProps {
  className?: string;
  panSpeed?: number;
  points?: { lat: number; lon: number }[];
}

export function DitherMap({ className = "", panSpeed = 0.00008, points }: DitherMapProps) {
  return (
    <div className={className}>
      <DitherMapCanvas
        className="absolute inset-0 w-full h-full"
        panSpeed={panSpeed}
        points={points}
      />
    </div>
  );
}
