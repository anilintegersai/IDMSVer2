import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import MergeTemplates from "./pages/MergeTemplates";
import InsertContent from "./pages/InsertContent";
import EditContent from "./pages/EditContent";
import TocViewer from "./pages/TocViewer";

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/merge-templates" replace />} />
          <Route path="/merge-templates" element={<MergeTemplates />} />
          <Route path="/insert-content" element={<InsertContent />} />
          <Route path="/edit-content" element={<EditContent />} />
          <Route path="/toc-viewer" element={<TocViewer />} />
          <Route path="*" element={<Navigate to="/merge-templates" replace />} />
        </Routes>
      </main>
    </div>
  );
}
