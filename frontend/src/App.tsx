import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import Layout from './components/Layout';

const ResumeListPage = () => import('./pages/ResumeListPage').then(m => m.default);
const ResumeDetailPage = () => import('./pages/ResumeDetailPage').then(m => m.default);
const UploadPage = () => import('./pages/UploadPage').then(m => m.default);
const InterviewHistoryPage = () => import('./pages/InterviewHistoryPage').then(m => m.default);
const InterviewDetailPage = () => import('./pages/InterviewDetailPage').then(m => m.default);
const InterviewHubPage = () => import('./pages/InterviewHubPage').then(m => m.default);
const InterviewPage = () => import('./pages/InterviewPage').then(m => m.default);
const KnowledgeBaseListPage = () => import('./pages/KnowledgeBaseListPage').then(m => m.default);
const KnowledgeBaseDetailPage = () => import('./pages/KnowledgeBaseDetailPage').then(m => m.default);
const KnowledgeBaseUploadPage = () => import('./pages/KnowledgeBaseUploadPage').then(m => m.default);

const Loading = () => (
  <div className="flex items-center justify-center min-h-[50vh]">
    <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
  </div>
);

function LazyPage({ loader }: { loader: () => Promise<any> }) {
  const [Component, setComponent] = React.useState<any>(null);
  React.useEffect(() => {
    loader().then(mod => setComponent(() => mod));
  }, [loader]);
  return Component ? <Component /> : <Loading />;
}

import React from 'react';

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/resumes" replace />} />
            <Route path="resumes" element={<LazyPage loader={ResumeListPage} />} />
            <Route path="resumes/:resumeId" element={<LazyPage loader={ResumeDetailPage} />} />
            <Route path="upload" element={<LazyPage loader={UploadPage} />} />
            <Route path="knowledgebases" element={<LazyPage loader={KnowledgeBaseListPage} />} />
            <Route path="knowledgebases/upload" element={<LazyPage loader={KnowledgeBaseUploadPage} />} />
            <Route path="knowledgebases/:kbId" element={<LazyPage loader={KnowledgeBaseDetailPage} />} />
            <Route path="interviews" element={<LazyPage loader={InterviewHistoryPage} />} />
            <Route path="interviews/:sessionId" element={<LazyPage loader={InterviewDetailPage} />} />
            <Route path="interview-hub" element={<LazyPage loader={InterviewHubPage} />} />
            <Route path="interview" element={<LazyPage loader={InterviewPage} />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
