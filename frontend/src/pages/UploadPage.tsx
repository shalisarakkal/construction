import { useState } from "react";
import { UploadComponent } from "../components/UploadComponent";
import { DocumentList } from "../components/DocumentList";

export function UploadPage() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="page">
      <h2>Upload documents</h2>
      <UploadComponent onUploaded={() => setRefreshKey((k) => k + 1)} />

      <h2>Processed documents</h2>
      <DocumentList refreshKey={refreshKey} />
    </div>
  );
}
