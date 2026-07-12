import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import MergeTemplates from "./pages/MergeTemplates";
import Placeholder from "./pages/Placeholder";

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/merge-templates" replace />} />
          <Route path="/merge-templates" element={<MergeTemplates />} />
          <Route
            path="/insert-section"
            element={
              <Placeholder
                title="Insert Section"
                description="Insert a new heading and body content into a document at a chosen location. This feature will be wired up next."
              />
            }
          />
          <Route
            path="/insert-content"
            element={
              <Placeholder
                title="Insert Content"
                description="Insert plain or formatted paragraphs into a document at a chosen location. This feature will be wired up next."
              />
            }
          />
          <Route path="*" element={<Navigate to="/merge-templates" replace />} />
        </Routes>
      </main>
    </div>
  );
}
