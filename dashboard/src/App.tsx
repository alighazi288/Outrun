import { useState } from "react";
import { WorldProvider } from "@/context/WorldContext";
import OutrunMap from "@/components/OutrunMap";
import Timeline from "@/components/Timeline";
import TopBar from "@/components/TopBar";
import RightPanel from "@/components/RightPanel";
import Footer from "@/components/Footer";

export default function App() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <WorldProvider>
      {/* Full-screen container */}
      <div style={{ width: "100vw", height: "100vh", position: "relative", background: "var(--bg)" }}>
        {/* Map fills entire viewport; UI panels float over it */}
        <OutrunMap
          selectedId={selectedId}
          onSelectResident={setSelectedId}
        />

        {/* Fixed UI chrome */}
        <TopBar />
        <RightPanel selectedId={selectedId} onSelectId={setSelectedId} />
        <Footer />
        <Timeline />
      </div>
    </WorldProvider>
  );
}
