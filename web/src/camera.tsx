// Barcode scanning with the device camera, for phones without a hardware
// scanner. Uses zxing (WebAssembly), bundled with the app so it works offline
// and on servers without internet access. Loaded only when the camera opens.

import { useEffect, useRef, useState } from "react";
import { prepareZXingModule, readBarcodes, type ReaderOptions } from "zxing-wasm/reader";
import wasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";

prepareZXingModule({
  overrides: {
    locateFile: (path: string, prefix: string) => (path.endsWith(".wasm") ? wasmUrl : prefix + path),
  },
});

const OPTIONS: ReaderOptions = {
  formats: ["Code128", "DataMatrix", "QRCode", "EAN13", "EAN8", "UPCA", "UPCE", "DataBar", "DataBarExp", "ITF14"],
  // Raw content plus the symbology identifier (e.g. "]C1" for GS1-128): the
  // server's parser then sees real FNC1 separators instead of guessing.
  textMode: "Plain",
  tryHarder: true,
  maxNumberOfSymbols: 1,
};

const GS1_IDENTIFIERS = ["]C1", "]e0", "]d2", "]Q3", "]J1"];

export default function CameraScanner({ onResult, onClose }: { onResult: (text: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let timer = 0;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    async function scanFrame() {
      const video = videoRef.current;
      if (stopped || !video || !ctx) return;
      if (video.readyState >= 2 && video.videoWidth) {
        // Scan the middle band, where the aiming guide is; faster and fewer misreads.
        const w = video.videoWidth;
        const h = Math.round(video.videoHeight * 0.5);
        canvas.width = w;
        canvas.height = h;
        ctx.drawImage(video, 0, (video.videoHeight - h) / 2, w, h, 0, 0, w, h);
        try {
          const [result] = await readBarcodes(ctx.getImageData(0, 0, w, h), OPTIONS);
          if (result?.isValid && result.text && !stopped) {
            const id = result.symbologyIdentifier;
            stopped = true;
            onResult(GS1_IDENTIFIERS.includes(id) ? id + result.text : result.text);
            return;
          }
        } catch (e) {
          setError(`Barcode reader failed to load: ${e instanceof Error ? e.message : e}`);
          return;
        }
      }
      timer = window.setTimeout(scanFrame, 120);
    }

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        });
        if (stopped || !videoRef.current) return;
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        scanFrame();
      } catch (e) {
        setError(
          e instanceof DOMException && e.name === "NotAllowedError"
            ? "Camera access was refused. Allow it in the browser's site settings."
            : `Camera not available: ${e instanceof Error ? e.message : e}`,
        );
      }
    })();

    return () => {
      stopped = true;
      window.clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onResult]);

  return (
    <div className="camera-overlay" role="dialog" aria-modal="true" aria-label="Scan with camera">
      <video ref={videoRef} className="camera-video" playsInline muted />
      <div className="camera-guide" aria-hidden="true" />
      <div className="camera-bar">
        <span>{error || "Point the camera at a barcode"}</span>
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
