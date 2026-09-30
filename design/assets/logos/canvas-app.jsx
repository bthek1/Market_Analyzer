/* global React, ReactDOM, LOGOS */
// Canvas app — renders each logo direction as an artboard inside a DCSection.

function ArtboardContent({ logo }) {
  const { Mark, name, note, tile } = logo;
  return (
    <div className="ab">
      <div className="ab-hero">
        {tile ? <Mark size={180} /> : <Mark size={160} />}
      </div>

      <div className="ab-strip">
        <div className="wordmark">
          <Mark size={28} />
          <span>Stock Market</span>
          <span className="sub">Analyser</span>
        </div>
      </div>

      <div className="ab-strip compact">
        <span className="lbl">Favicon</span>
        <div className="fav-strip">
          <div className="fav"><Mark size={32} /></div>
          <div className="fav"><Mark size={20} /></div>
          <div className="fav"><Mark size={14} /></div>
        </div>
      </div>

      <div className="ab-strip" style={{background: "#0b1220", borderTop: "1px solid #1f2937"}}>
        <div className="wordmark dark">
          <Mark size={28} inverse />
          <span>Stock Market</span>
          <span className="sub">Analyser</span>
        </div>
      </div>

      <div className="ab-strip compact" style={{background: "#fafafa"}}>
        <span className="lbl" style={{margin: 0}}>{note}</span>
      </div>
    </div>
  );
}

function App() {
  return (
    <DesignCanvas defaultZoom={0.5}>
      <DCSection id="logos" title="Logo directions" subtitle="Six routes. Pick one (or mix), and I'll refine + replace the placeholders across the system.">
        {LOGOS.map((logo) => (
          <DCArtboard
            key={logo.id}
            id={logo.id}
            label={logo.name}
            width={540}
            height={640}
          >
            <ArtboardContent logo={logo} />
          </DCArtboard>
        ))}
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
