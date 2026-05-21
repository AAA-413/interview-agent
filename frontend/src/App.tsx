import React, { lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import Layout from './components/Layout';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const InterviewDiagnosisPage = lazy(() => import('./pages/InterviewDiagnosisPage'));
const ProjectDrillPage = lazy(() => import('./pages/ProjectDrillPage'));
const ResumeListPage = lazy(() => import('./pages/ResumeListPage'));
const ResumeDetailPage = lazy(() => import('./pages/ResumeDetailPage'));
const UploadPage = lazy(() => import('./pages/UploadPage'));
const InterviewHistoryPage = lazy(() => import('./pages/InterviewHistoryPage'));
const InterviewDetailPage = lazy(() => import('./pages/InterviewDetailPage'));
const InterviewHubPage = lazy(() => import('./pages/InterviewHubPage'));
const InterviewPage = lazy(() => import('./pages/InterviewPage'));
const KnowledgeBaseListPage = lazy(() => import('./pages/KnowledgeBaseListPage'));
const KnowledgeBaseDetailPage = lazy(() => import('./pages/KnowledgeBaseDetailPage'));
const KnowledgeBaseUploadPage = lazy(() => import('./pages/KnowledgeBaseUploadPage'));
const SmartDownloadPage = lazy(() => import('./pages/SmartDownloadPage'));
const KnowledgeGraphPage = lazy(() => import('./pages/KnowledgeGraphPage'));

const Loading = () => (
  <div className="flex items-center justify-center min-h-[50vh]">
    <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
  </div>
);

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/diagnosis" replace />} />
            <Route path="diagnosis" element={<InterviewDiagnosisPage />} />
            <Route path="project-drill" element={<ProjectDrillPage />} />
            <Route path="resumes" element={<ResumeListPage />} />
            <Route path="resumes/:resumeId" element={<ResumeDetailPage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="knowledgebases" element={<KnowledgeBaseListPage />} />
            <Route path="knowledgebases/upload" element={<KnowledgeBaseUploadPage />} />
            <Route path="knowledgebases/smart-download" element={<SmartDownloadPage />} />
            <Route path="knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route path="knowledgebases/:kbId" element={<KnowledgeBaseDetailPage />} />
            <Route path="interviews" element={<InterviewHistoryPage />} />
            <Route path="interviews/:sessionId" element={<InterviewDetailPage />} />
            <Route path="interview-hub" element={<InterviewHubPage />} />
            <Route path="interview" element={<InterviewPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
