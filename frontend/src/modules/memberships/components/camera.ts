/** Reading a QR code or barcode with the device camera, only where the browser can (feature-detected, never assumed). */
export interface Detector { detect(source: CanvasImageSource): Promise<{ rawValue: string }[]> }
type DetectorConstructor = new (options?: { formats?: string[] }) => Detector;

export function cameraScanSupported(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  return "BarcodeDetector" in window && typeof navigator.mediaDevices?.getUserMedia === "function";
}

export function makeDetector(): Detector | null {
  try {
    const Ctor = (window as unknown as { BarcodeDetector?: DetectorConstructor }).BarcodeDetector;
    return Ctor ? new Ctor({ formats: ["qr_code", "code_128", "code_39", "ean_13", "ean_8", "upc_a", "itf"] }) : null;
  } catch {
    return null;
  }
}
