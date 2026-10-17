import { useState } from "react";
import { WorldProvider } from "@/context/WorldContext";
import OutrunMap from "@/components/OutrunMap";
import Timeline from "@/components/Timeline";
import TopBar from "@/components/TopBar";
import AreaBanner from "@/components/AreaBanner";
import RightPanel from "@/components/RightPanel";
import Footer from "@/components/Footer";
import LivePicker from "@/components/LivePicker";
import ModeSwitch from "@/components/ModeSwitch";
import { routeSearch, useRoute } from "@/route";
import topBar from "@/components/TopBar.module.css";

export default function App() {
  const [route, setRoute] = useRoute();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Live mode with no area chosen yet: pick a real fire or a place first.
  if (route.mode === "live" && !route.area) {
    return (
      <>
        <header className={topBar.bar} style={{ right: 0 }}>
          <div className={topBar.title}>Outrun</div>
          <ModeSwitch route={route} onRoute={setRoute} />
        </header>
        <LivePicker onOpen={(area) => setRoute({ mode: "live", area })} />
      </>
    );
  }

  return (
    // A new provider (and data source) per screen; the old one is closed.
    <WorldProvider key={routeSearch(route)} route={route}>
      {/* Full-screen container */}
      <div style={{ width: "100vw", height: "100vh", position: "relative", background: "var(--bg)" }}>
        {/* Map fills entire viewport; UI panels float over it */}
        <OutrunMap
          selectedId={selectedId}
          onSelectResident={setSelectedId}
        />

        {/* Fixed UI chrome */}
        <TopBar onRoute={setRoute} />
        <AreaBanner />
        <RightPanel selectedId={selectedId} onSelectId={setSelectedId} />
        <Footer />
        <Timeline />
      </div>
    </WorldProvider>
  );
}
