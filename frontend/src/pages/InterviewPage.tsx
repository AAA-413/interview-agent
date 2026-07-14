import { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  ArrowLeft,
  Send,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock3,
  Mic,
  MicOff,
  Lightbulb,
  RotateCcw,
  Trophy,
  BookOpenCheck,
  Library,
} from 'lucide-react';
import { interviewApi } from '../api/interview';
import {
  VOICE_ERROR_MESSAGES,
  cleanTranscript,
  getAudioFileExtension,
  getPreferredAudioMimeType,
} from '../utils/voice';
import type {
  DynamicCoachHint,
  DynamicReportDTO,
  DynamicSessionDetailDTO,
  DynamicTopicRagInsightDTO,
  DynamicTopicDTO,
  DynamicTurnDTO,
  InterviewQuestionDTO,
  InterviewSessionDTO,
  InterviewReportDTO,
} from '../types/interview';

const PROCESSING_STATUSES = new Set(['PENDING', 'PROCESSING']);

type VoiceState = 'idle' | 'recording' | 'transcribing';
type DynamicReviewItem = { turn: DynamicTurnDTO; answer: string; score: number | null };

const dynamicTypeLabel: Record<string, string> = {
  PROJECT: '项目',
  KNOWLEDGE: '知识',
  SYSTEM_DESIGN: '系统设计',
};

const dynamicTurnTypeLabel: Record<string, string> = {
  MAIN: '主问题',
  FOLLOW_UP: '追问',
  COACH_RETRY: '重答',
};

const dynamicAbilityLabel: Record<string, string> = {
  authenticity: '真实性证据',
  technical_depth: '技术深度',
  knowledge_accuracy: '知识准确性',
  system_thinking: '系统思维',
  communication_structure: '表达结构',
};

const dynamicSignalGroups = [
  { key: 'strengths', label: '亮点', className: 'bg-green-50 text-green-700' },
  { key: 'gaps', label: '缺口', className: 'bg-amber-50 text-amber-700' },
  { key: 'risks', label: '风险', className: 'bg-red-50 text-red-700' },
];

const defaultDynamicPlanningStages = [
  { key: 'RESUME_PROFILE', label: '正在分析简历项目', status: 'COMPLETED' },
  { key: 'JD_PARSE', label: '正在匹配 JD 重点', status: 'ACTIVE' },
  { key: 'TOPIC_PLAN', label: '正在选择面试主题', status: 'PENDING' },
  { key: 'MAIN_QUESTION_GENERATE', label: '正在准备第一题', status: 'PENDING' },
];

const getDynamicPlanningStages = (summary: Record<string, unknown> | undefined) => {
  const stages = summary?.generation_stages;
  if (!Array.isArray(stages)) return defaultDynamicPlanningStages;
  return stages.map((stage, index) => {
    if (!stage || typeof stage !== 'object') return defaultDynamicPlanningStages[index] || defaultDynamicPlanningStages[0];
    const item = stage as Record<string, unknown>;
    return {
      key: typeof item.key === 'string' ? item.key : `stage-${index}`,
      label: typeof item.label === 'string' ? item.label : defaultDynamicPlanningStages[index]?.label || '准备中',
      status: typeof item.status === 'string' ? item.status : 'PENDING',
    };
  });
};

const scoreBadgeClass = (score: number | null | undefined) => {
  if (score === null || score === undefined) return 'bg-slate-100 text-slate-500';
  if (score >= 80) return 'bg-green-100 text-green-700';
  if (score >= 60) return 'bg-amber-100 text-amber-700';
  return 'bg-red-100 text-red-700';
};

const ragSourceLabel: Record<string, string> = {
  PERSONAL_KB_HIT: '个人知识库',
  SYSTEM_KB_HIT: '系统资料',
  MIXED_HIT: '混合资料',
  NO_KB_HIT: '未引用资料',
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const dynamicTurnKey = (turn: DynamicTurnDTO) =>
  turn.id ? `turn-${turn.id}` : `${turn.topic_id || 'topic'}-${turn.turn_order}-${turn.question}`;

const getDynamicDimensionScores = (turn: DynamicTurnDTO) => {
  const dimensionScores = isRecord(turn.evaluation) ? turn.evaluation.dimension_scores : null;
  if (!isRecord(dimensionScores)) return [];
  return Object.entries(dimensionScores)
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
    .map(([key, value]) => ({ key, label: dynamicAbilityLabel[key] || key, value }));
};

export default function InterviewPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { sessionId?: string; sessionIdToResume?: string; mode?: 'static' | 'dynamic' } | null;
  const searchParams = new URLSearchParams(location.search);
  const sessionIdFromQuery = searchParams.get('sessionId');
  const modeFromQuery = searchParams.get('mode');
  const sessionIdFromState = state?.sessionId || state?.sessionIdToResume || sessionIdFromQuery;
  const storedMode = sessionIdFromState ? sessionStorage.getItem(`interview_mode_${sessionIdFromState}`) : null;
  const isDynamic = state?.mode === 'dynamic' || modeFromQuery === 'dynamic' || storedMode === 'dynamic';

  const [sessionId, setSessionId] = useState<string | null>(sessionIdFromState || null);
  const [session, setSession] = useState<InterviewSessionDTO | null>(null);
  const [dynamicSession, setDynamicSession] = useState<DynamicSessionDetailDTO | null>(null);
  const [dynamicTurn, setDynamicTurn] = useState<DynamicTurnDTO | null>(null);
  const [dynamicTopic, setDynamicTopic] = useState<DynamicTopicDTO | null>(null);
  const [dynamicReport, setDynamicReport] = useState<DynamicReportDTO | null>(null);
  const [dynamicHint, setDynamicHint] = useState<DynamicCoachHint | null>(null);
  const [dynamicFeedback, setDynamicFeedback] = useState('');
  const [currentQuestion, setCurrentQuestion] = useState<InterviewQuestionDTO | null>(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [voiceError, setVoiceError] = useState('');
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [report, setReport] = useState<InterviewReportDTO | null>(null);
  const [questionHistory, setQuestionHistory] = useState<{ question: InterviewQuestionDTO; answer: string }[]>([]);
  const [dynamicHistory, setDynamicHistory] = useState<{ turn: DynamicTurnDTO; answer: string; score: number | null }[]>([]);
  const [ragInsightByTopic, setRagInsightByTopic] = useState<Record<number, DynamicTopicRagInsightDTO>>({});
  const [ragLoadingTopicId, setRagLoadingTopicId] = useState<number | null>(null);
  const [retryingDynamicTopicId, setRetryingDynamicTopicId] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const shouldTranscribeRef = useRef(false);

  useEffect(() => {
    if (!sessionId) {
      navigate('/interview-hub');
      return;
    }
    if (isDynamic) {
      void loadDynamicSession(true);
      return;
    }
    void loadSession(true);
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !isDynamic || dynamicSession?.status !== 'PLANNING') {
      return;
    }

    const timer = window.setInterval(() => {
      void loadDynamicSession(false);
    }, 2000);

    return () => window.clearInterval(timer);
  }, [sessionId, isDynamic, dynamicSession?.status]);

  useEffect(() => {
    if (!sessionId || !completed || report) {
      return;
    }

    const timer = window.setInterval(() => {
      void pollReport();
    }, 3000);

    return () => window.clearInterval(timer);
  }, [sessionId, completed, report]);

  useEffect(() => {
    return () => {
      shouldTranscribeRef.current = false;
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      releaseVoiceStream();
      clearRecordingTimer();
    };
  }, []);

  const loadSession = async (showLoading = false) => {
    if (!sessionId) return;

    if (showLoading) {
      setLoading(true);
    }

    try {
      const s = await interviewApi.getSession(sessionId);
      setSession(s);

      if (s.status === 'COMPLETED' || s.status === 'EVALUATED') {
        setCompleted(true);
        setCurrentQuestion(null);

        if (s.status === 'EVALUATED') {
          const r = await interviewApi.getReport(sessionId);
          setReport(r);
          setError('');
        } else {
          setReport(null);
          if (s.evaluate_status === 'FAILED') {
            setError(s.evaluate_error || '面试报告生成失败');
          } else {
            setError('');
          }
        }
        return;
      }

      const q = await interviewApi.getCurrentQuestion(sessionId);
      if (q.completed) {
        setCompleted(true);
        setCurrentQuestion(null);
        setReport(null);
        setError('');
      } else if (q.question) {
        setCurrentQuestion(q.question);
        setCompleted(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const loadDynamicSession = async (showLoading = false) => {
    if (!sessionId) return;

    if (showLoading) {
      setLoading(true);
    }

    try {
      const detail = await interviewApi.getDynamicSession(sessionId);
      setDynamicSession(detail);
      setDynamicTopic(detail.current_topic);
      setDynamicTurn(detail.current_turn);
      setDynamicReport(detail.final_report);
      setCompleted(detail.status === 'COMPLETED' || Boolean(detail.final_report));
      setDynamicHistory(
        detail.turns
          .filter(turn => turn.answer)
          .map(turn => ({ turn, answer: turn.answer || '', score: turn.ability_score }))
      );
      if (detail.status === 'FAILED') {
        const generationError = detail.plan_summary.generation_error;
        setError(typeof generationError === 'string' ? generationError : '面试计划生成失败，可以返回创建页重试');
      } else {
        setError('');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const pollReport = async () => {
    if (!sessionId) return;

    try {
      const s = await interviewApi.getSession(sessionId);
      setSession(s);

      if (s.status === 'EVALUATED') {
        const r = await interviewApi.getReport(sessionId);
        setReport(r);
        setError('');
        return;
      }

      if (s.evaluate_status === 'FAILED') {
        setError(s.evaluate_error || '面试报告生成失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载报告失败');
    }
  };

  const appendTranscript = (text: string) => {
    const transcript = cleanTranscript(text);
    if (!transcript) return;

    setAnswer(prev => {
      const current = prev.trimEnd();
      if (!current) return transcript;
      const separator = /[。！？!?.,，；;:]$/.test(current) ? '\n' : ' ';
      return `${current}${separator}${transcript}`;
    });

    window.setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const clearRecordingTimer = () => {
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  };

  const releaseVoiceStream = () => {
    mediaStreamRef.current?.getTracks().forEach(track => track.stop());
    mediaStreamRef.current = null;
  };

  const transcribeAudioBlob = async (blob: Blob) => {
    if (blob.size < 1024) {
      setVoiceError('录音时间太短，可以再说一次');
      setVoiceState('idle');
      return;
    }

    setVoiceState('transcribing');
    setVoiceError('');
    try {
      const mimeType = blob.type || 'audio/webm';
      const extension = getAudioFileExtension(mimeType);
      const audioFile = new File([blob], `interview-answer-${Date.now()}.${extension}`, { type: mimeType });
      const result = await interviewApi.transcribeVoice(audioFile);
      const transcript = cleanTranscript(result.text);
      if (!transcript) {
        setVoiceError('这段录音没有识别出文字，可以靠近麦克风再试一次');
        return;
      }
      appendTranscript(transcript);
    } catch (err) {
      setVoiceError(err instanceof Error ? err.message : '语音转文字失败，请重新录音或手动输入');
    } finally {
      setVoiceState('idle');
      setRecordingSeconds(0);
    }
  };

  const stopVoiceRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    recorder.stop();
  };

  const startVoiceRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setVoiceError('当前浏览器不支持录音，请换 Chrome/Edge 或手动输入');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const mimeType = getPreferredAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

      audioChunksRef.current = [];
      shouldTranscribeRef.current = true;
      mediaStreamRef.current = stream;
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = event => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        setVoiceError('录音失败，请重新授权麦克风或手动输入');
        setVoiceState('idle');
        clearRecordingTimer();
        releaseVoiceStream();
      };

      recorder.onstop = () => {
        clearRecordingTimer();
        releaseVoiceStream();
        const shouldTranscribe = shouldTranscribeRef.current;
        shouldTranscribeRef.current = false;
        mediaRecorderRef.current = null;

        if (!shouldTranscribe) return;
        const audioType = recorder.mimeType || mimeType || 'audio/webm';
        const blob = new Blob(audioChunksRef.current, { type: audioType });
        audioChunksRef.current = [];
        void transcribeAudioBlob(blob);
      };

      setVoiceError('');
      setRecordingSeconds(0);
      setVoiceState('recording');
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds(value => value + 1);
      }, 1000);
      recorder.start(1000);
    } catch (err) {
      const name = err instanceof DOMException ? err.name : '';
      setVoiceError(VOICE_ERROR_MESSAGES[name] || '无法打开麦克风，请检查权限后再试');
      setVoiceState('idle');
      clearRecordingTimer();
      releaseVoiceStream();
    }
  };

  const toggleVoiceInput = () => {
    if (voiceState === 'recording') {
      stopVoiceRecording();
      return;
    }
    if (voiceState === 'idle') {
      void startVoiceRecording();
    }
  };

  const loadRagInsight = async (topicId: number | null | undefined) => {
    if (!sessionId || !topicId || ragLoadingTopicId === topicId) return;
    setRagLoadingTopicId(topicId);
    setError('');
    try {
      const insight = await interviewApi.getDynamicTopicRagInsight(sessionId, topicId);
      setRagInsightByTopic(prev => ({ ...prev, [topicId]: insight }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载讲解失败');
    } finally {
      setRagLoadingTopicId(null);
    }
  };

  const handleDynamicTopicRetry = async (topicId: number | null | undefined) => {
    if (!sessionId || !topicId || retryingDynamicTopicId !== null) return;
    setRetryingDynamicTopicId(topicId);
    setError('');
    try {
      const retrySession = await interviewApi.createDynamicTopicRetrySession(sessionId, topicId);
      sessionStorage.setItem(`interview_mode_${retrySession.session_id}`, 'dynamic');
      setSessionId(retrySession.session_id);
      setSession(null);
      setCurrentQuestion(null);
      setReport(null);
      setDynamicSession(null);
      setDynamicTopic(retrySession.current_topic);
      setDynamicTurn(retrySession.current_turn);
      setDynamicReport(null);
      setDynamicHint(null);
      setDynamicFeedback('');
      setDynamicHistory([]);
      setRagInsightByTopic({});
      setAnswer('');
      setCompleted(false);
      navigate('/interview', { state: { sessionId: retrySession.session_id, mode: 'dynamic' } });
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建重练失败');
    } finally {
      setRetryingDynamicTopicId(null);
    }
  };

  const handleSubmit = async () => {
    if (isDynamic) {
      await handleDynamicSubmit();
      return;
    }

    if (!sessionId || !answer.trim() || submitting || !currentQuestion || voiceState !== 'idle') return;
    setSubmitting(true);
    setError('');
    try {
      const trimmedAnswer = answer.trim();
      const response = await interviewApi.submitAnswer(sessionId, currentQuestion.question_index, trimmedAnswer);
      setQuestionHistory(prev => [...prev, { question: currentQuestion, answer: trimmedAnswer }]);
      setAnswer('');

      if (response.has_next_question && response.next_question) {
        setCurrentQuestion(response.next_question);
      } else {
        setCompleted(true);
        setCurrentQuestion(null);
        setReport(null);
        await loadSession(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDynamicSubmit = async () => {
    if (!sessionId || !answer.trim() || submitting || !dynamicTurn?.id || voiceState !== 'idle') return;
    setSubmitting(true);
    setError('');
    try {
      const trimmedAnswer = answer.trim();
      const response = await interviewApi.submitDynamicTurnAnswer(sessionId, dynamicTurn.id, { answer: trimmedAnswer });
      const answeredTurn: DynamicTurnDTO = {
        ...dynamicTurn,
        answer: trimmedAnswer,
        ability_score: response.evaluation.ability_score,
        feedback: response.evaluation.feedback,
        signals: response.evaluation.signals,
        evaluation: {
          ...dynamicTurn.evaluation,
          dimension_scores: response.evaluation.dimension_scores,
        },
        decision: { ...response.decision },
        coach_hint: response.decision.hint,
      };
      setDynamicHistory(prev => [
        ...prev,
        { turn: answeredTurn, answer: trimmedAnswer, score: response.evaluation.ability_score },
      ]);
      setDynamicFeedback(response.evaluation.feedback);
      setDynamicHint(response.decision.hint);
      setAnswer('');

      if (response.report) {
        setDynamicReport(response.report);
        setCompleted(true);
        setDynamicTurn(null);
      } else {
        setDynamicTurn(response.next_turn);
        setDynamicTopic(response.current_topic);
        if (!response.next_turn) {
          setCompleted(true);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const renderRagInsight = (topicId: number | null | undefined) => {
    if (!topicId) return null;
    const insight = ragInsightByTopic[topicId];
    if (!insight) return null;
    return (
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
            {ragSourceLabel[insight.source_status] || insight.source_status}
          </span>
          <span className="text-xs text-slate-400">置信度 {Math.round(insight.retrieval_confidence * 100)}%</span>
        </div>
        {insight.fallback_reason && <p className="mb-2 text-xs text-slate-500">{insight.fallback_reason}</p>}
        <p className="mb-2 text-sm leading-6 text-slate-700">{insight.explanation}</p>
        <p className="mb-3 text-xs text-amber-700">扣分解释：{insight.answer_issue}</p>
        {insight.citations.length > 0 && (
          <div className="mb-3 space-y-2">
            {insight.citations.map(citation => (
              <div key={`${citation.knowledge_base_id}-${citation.chunk_id}`} className="rounded-lg bg-white p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-slate-700">{citation.source_name}</span>
                  <span className="text-xs text-slate-400">{Math.round(citation.score * 100)}%</span>
                </div>
                <p className="line-clamp-2 text-xs leading-5 text-slate-500">{citation.content_preview}</p>
              </div>
            ))}
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-medium text-slate-500">推荐资料</p>
            <div className="flex flex-wrap gap-2">
              {insight.recommended_materials.map(item => (
                <span key={item} className="rounded-md bg-white px-2 py-1 text-xs text-slate-600">{item}</span>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs font-medium text-slate-500">学习路径</p>
            <div className="space-y-1">
              {insight.study_steps.map((step, index) => (
                <p key={step} className="text-xs text-slate-600">{index + 1}. {step}</p>
              ))}
            </div>
          </div>
        </div>
        <p className="mt-3 text-xs font-medium text-primary-700">{insight.next_practice}</p>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
      </div>
    );
  }

  if (isDynamic && dynamicSession?.status === 'PLANNING') {
    const stages = getDynamicPlanningStages(dynamicSession.plan_summary);
    const dynamicModeLabel = dynamicSession.mode === 'STRICT' ? '严厉模式' : '教练模式';
    return (
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center gap-3">
          <button onClick={() => navigate('/interview-hub')} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div>
            <h1 className="text-lg font-bold text-slate-900">{dynamicModeLabel}</h1>
            <p className="text-sm text-slate-400">面试计划生成中</p>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="mb-5 flex items-center gap-3">
            <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
            <span className="font-medium text-slate-900">正在准备第一题</span>
          </div>
          <div className="space-y-3">
            {stages.map(stage => (
              <div key={stage.key} className="flex items-center gap-3">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    stage.status === 'COMPLETED'
                      ? 'bg-green-500'
                      : stage.status === 'ACTIVE'
                        ? 'bg-primary-500'
                        : stage.status === 'FAILED'
                          ? 'bg-red-500'
                          : 'bg-slate-200'
                  }`}
                />
                <span className="text-sm text-slate-600">{stage.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (isDynamic && dynamicSession?.status === 'FAILED') {
    return (
      <div className="mx-auto max-w-2xl">
        <div className="rounded-2xl border border-red-100 bg-red-50 p-6">
          <div className="mb-3 flex items-center gap-2 font-semibold text-red-700">
            <AlertCircle className="h-5 w-5" />
            面试计划生成失败
          </div>
          <p className="text-sm leading-6 text-red-700">{error || '可以返回创建页重试，已保存这次会话配置。'}</p>
          <button
            onClick={() => navigate('/interview-hub')}
            className="mt-5 rounded-xl bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
          >
            返回创建页
          </button>
        </div>
      </div>
    );
  }

  if (isDynamic && completed && dynamicReport) {
    const topicIdByKey = new Map(dynamicReport.topic_summaries.map(summary => [summary.topic_key, summary.topic_id]));
    const dynamicModeLabel = dynamicSession?.mode === 'STRICT' ? '严厉模式' : '教练模式';
    const reviewItemsByKey = new Map<string, DynamicReviewItem>();
    (dynamicSession?.turns || [])
      .filter(turn => turn.answer)
      .forEach(turn => {
        reviewItemsByKey.set(dynamicTurnKey(turn), {
          turn,
          answer: turn.answer || '',
          score: turn.ability_score,
        });
      });
    dynamicHistory
      .filter(item => item.answer)
      .forEach(item => reviewItemsByKey.set(dynamicTurnKey(item.turn), item));
    const reviewItemsByTopic = new Map<number, DynamicReviewItem[]>();
    Array.from(reviewItemsByKey.values()).forEach(item => {
      if (!item.turn.topic_id) return;
      const items = reviewItemsByTopic.get(item.turn.topic_id) || [];
      items.push(item);
      reviewItemsByTopic.set(item.turn.topic_id, items);
    });
    reviewItemsByTopic.forEach(items => {
      items.sort((a, b) => a.turn.turn_order - b.turn.turn_order);
    });
    const showHistoricalCoachHints = dynamicSession?.mode === 'COACH';

    return (
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 text-center">
          <Trophy className="mx-auto mb-4 h-16 w-16 text-primary-500" />
          <h1 className="text-2xl font-bold text-slate-900">{dynamicModeLabel}完成</h1>
          <p className="mt-2 text-slate-500">已按 topic 汇总表现，保留每轮题目、回答和点评</p>
        </div>

        <div className="mb-6 grid gap-4 md:grid-cols-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 md:col-span-1">
            <p className="text-sm text-slate-500">综合准备度</p>
            <p className="mt-2 text-4xl font-bold text-primary-600">{dynamicReport.readiness_score}</p>
          </div>
          {Object.entries(dynamicReport.type_scores).map(([type, score]) => (
            <div key={type} className="rounded-2xl border border-slate-200 bg-white p-5">
              <p className="text-sm text-slate-500">{dynamicTypeLabel[type.toUpperCase()] || type}</p>
              <p className="mt-2 text-3xl font-bold text-slate-900">{score ?? '-'}</p>
            </div>
          ))}
        </div>

        {dynamicReport.top_risks.length > 0 && (
          <div className="mb-6 rounded-2xl border border-red-100 bg-red-50 p-5">
            <h2 className="mb-3 font-semibold text-red-700">Top 3 风险</h2>
            <div className="space-y-2">
              {dynamicReport.top_risks.map((risk, index) => (
                <p key={index} className="text-sm text-red-700">{index + 1}. {risk}</p>
              ))}
            </div>
          </div>
        )}

        <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="mb-4 font-semibold text-slate-900">明日 3 件事</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {dynamicReport.tomorrow_tasks.map((task, index) => {
              const topicId = topicIdByKey.get(task.topic_key);
              return (
                <div key={`${task.topic_key}-${index}`} className="rounded-xl border border-slate-200 p-4">
                  <span className="rounded-full bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-700">
                    {task.task_type}
                  </span>
                  <h3 className="mt-3 text-sm font-semibold text-slate-900">{task.title}</h3>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{task.action}</p>
                  {topicId && (
                    <button
                      onClick={() => void loadRagInsight(topicId)}
                      disabled={ragLoadingTopicId === topicId}
                      className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      {ragLoadingTopicId === topicId ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Library className="h-3.5 w-3.5" />}
                      相关资料
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="mb-8 space-y-4">
          <h2 className="text-lg font-semibold text-slate-900">Topic 复盘</h2>
          {dynamicReport.topic_summaries.map(summary => {
            const reviewItems = summary.topic_id ? reviewItemsByTopic.get(summary.topic_id) || [] : [];
            return (
              <div key={summary.topic_key} className="rounded-2xl border border-slate-200 bg-white p-5">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold text-slate-900">{summary.topic_title}</h3>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {dynamicTypeLabel[summary.question_type] || summary.question_type}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${scoreBadgeClass(summary.final_score)}`}>
                    {summary.final_score ?? '-'} 分
                  </span>
                  {summary.score_delta !== null && (
                    <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                      提升 {summary.score_delta > 0 ? '+' : ''}{summary.score_delta}
                    </span>
                  )}
                </div>
                <p className="mb-3 text-sm text-slate-600">{summary.next_training_action}</p>
                {summary.gaps.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {summary.gaps.map((gap, index) => (
                      <span key={index} className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700">{gap}</span>
                    ))}
                  </div>
                )}

                <div className="mt-5 border-t border-slate-100 pt-4">
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-semibold text-slate-900">逐题问答</h4>
                    <span className="text-xs text-slate-400">{reviewItems.length || 1} 轮记录</span>
                  </div>
                  {reviewItems.length > 0 ? (
                    <div className="divide-y divide-slate-100">
                      {reviewItems.map(item => {
                        const dimensionScores = getDynamicDimensionScores(item.turn);
                        const coachHint = showHistoricalCoachHints ? item.turn.coach_hint : null;
                        return (
                          <div key={dynamicTurnKey(item.turn)} className="py-4 first:pt-2 last:pb-0">
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                                {dynamicTurnTypeLabel[item.turn.turn_type] || item.turn.turn_type}
                              </span>
                              <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${scoreBadgeClass(item.score)}`}>
                                {item.score ?? '-'} 分
                              </span>
                              {item.turn.decision_action && (
                                <span className="rounded-md bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
                                  {item.turn.decision_action}
                                </span>
                              )}
                            </div>
                            <p className="text-sm font-medium leading-6 text-slate-900">{item.turn.question}</p>
                            <div className="mt-3 border-l-2 border-slate-200 pl-3">
                              <div className="mb-1 text-xs font-semibold text-slate-500">你的回答</div>
                              <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{item.answer}</p>
                            </div>
                            {item.turn.feedback && (
                              <div className="mt-3 border-l-2 border-primary-200 pl-3">
                                <div className="mb-1 text-xs font-semibold text-primary-700">点评</div>
                                <p className="text-sm leading-6 text-slate-700">{item.turn.feedback}</p>
                              </div>
                            )}
                            {dimensionScores.length > 0 && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {dimensionScores.map(dimension => (
                                  <span key={dimension.key} className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-700">
                                    {dimension.label} {dimension.value}
                                  </span>
                                ))}
                              </div>
                            )}
                            <div className="mt-3 space-y-2">
                              {dynamicSignalGroups.map(group => {
                                const values = item.turn.signals?.[group.key] || [];
                                if (values.length === 0) return null;
                                return (
                                  <div key={group.key} className="flex flex-wrap items-center gap-2">
                                    <span className="text-xs font-medium text-slate-400">{group.label}</span>
                                    {values.slice(0, 4).map(value => (
                                      <span key={value} className={`rounded-md px-2 py-1 text-xs ${group.className}`}>{value}</span>
                                    ))}
                                  </div>
                                );
                              })}
                            </div>
                            {coachHint && (
                              <div className="mt-3 border-l-2 border-amber-200 pl-3">
                                <div className="mb-1 text-xs font-semibold text-amber-700">当时的教练提示</div>
                                {coachHint.message && <p className="text-sm leading-6 text-slate-700">{coachHint.message}</p>}
                                {coachHint.structure && (
                                  <div className="mt-2 flex flex-wrap gap-2">
                                    {coachHint.structure.map(item => (
                                      <span key={item} className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-700">{item}</span>
                                    ))}
                                  </div>
                                )}
                                {coachHint.focus_gaps && coachHint.focus_gaps.length > 0 && (
                                  <p className="mt-2 text-xs text-amber-700">重点补齐：{coachHint.focus_gaps.join('、')}</p>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="mt-3 border-l-2 border-slate-200 pl-3">
                      <div className="mb-1 text-xs font-semibold text-slate-500">主问题</div>
                      <p className="text-sm leading-6 text-slate-700">{summary.main_question}</p>
                    </div>
                  )}
                </div>

                {summary.topic_id && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      onClick={() => void loadRagInsight(summary.topic_id)}
                      disabled={ragLoadingTopicId === summary.topic_id}
                      className="inline-flex items-center gap-2 rounded-lg bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100 disabled:cursor-not-allowed disabled:text-primary-300"
                    >
                      {ragLoadingTopicId === summary.topic_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookOpenCheck className="h-4 w-4" />}
                      查看题解
                    </button>
                    <button
                      onClick={() => void loadRagInsight(summary.topic_id)}
                      disabled={ragLoadingTopicId === summary.topic_id}
                      className="inline-flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      <Library className="h-4 w-4" />
                      推荐资料
                    </button>
                    <button
                      onClick={() => void handleDynamicTopicRetry(summary.topic_id)}
                      disabled={retryingDynamicTopicId === summary.topic_id}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-200"
                    >
                      {retryingDynamicTopicId === summary.topic_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                      重练此题
                    </button>
                  </div>
                )}
                {renderRagInsight(summary.topic_id)}
              </div>
            );
          })}
        </div>

        <div className="flex gap-3">
          <button onClick={() => navigate('/interviews')} className="flex-1 rounded-xl bg-slate-100 py-3 font-medium text-slate-700 hover:bg-slate-200">
            查看所有记录
          </button>
          <button onClick={() => navigate('/interview-hub')} className="flex-1 rounded-xl bg-gradient-to-r from-primary-600 to-primary-500 py-3 font-medium text-white shadow-lg shadow-primary-500/25">
            再练一次
          </button>
        </div>
      </div>
    );
  }

  if (isDynamic) {
    const topicProgress = dynamicSession?.topics || [];
    const answeredCount = topicProgress.filter(topic => topic.status === 'COMPLETED').length;
    const dynamicModeLabel = dynamicSession?.mode === 'STRICT' ? '严厉模式' : '教练模式';
    const showCoachFeedback = dynamicSession?.mode !== 'STRICT' && (dynamicHint || dynamicFeedback);

    return (
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-center gap-3">
          <button onClick={() => navigate('/interview-hub')} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="flex-1">
            <h1 className="text-lg font-bold text-slate-900">{dynamicModeLabel}</h1>
            <p className="text-sm text-slate-400">Topic {dynamicTopic?.topic_order || '?'} / {topicProgress.length || 4}</p>
          </div>
        </div>

        <div className="mb-6 grid gap-2 sm:grid-cols-4">
          {topicProgress.map(topic => (
            <div
              key={topic.topic_key}
              className={`rounded-xl border p-3 ${
                topic.status === 'ACTIVE'
                  ? 'border-primary-300 bg-primary-50'
                  : topic.status === 'COMPLETED'
                    ? 'border-green-200 bg-green-50'
                    : 'border-slate-200 bg-white'
              }`}
            >
              <p className="truncate text-xs font-medium text-slate-700">{topic.topic_title}</p>
              <p className="mt-1 text-xs text-slate-400">{dynamicTypeLabel[topic.question_type] || topic.question_type}</p>
            </div>
          ))}
        </div>

        {dynamicHistory.length > 0 && (
          <div className="mb-6 max-h-64 space-y-3 overflow-y-auto">
            {dynamicHistory.map((item, index) => (
              <div key={`${item.turn.id}-${index}`} className="rounded-xl bg-slate-50 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700">
                    {item.turn.turn_type === 'COACH_RETRY' ? '重答' : item.turn.turn_type === 'FOLLOW_UP' ? '追问' : '主问题'}
                  </span>
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${scoreBadgeClass(item.score)}`}>
                    {item.score ?? '-'} 分
                  </span>
                </div>
                <p className="line-clamp-2 text-sm text-slate-500">{item.answer}</p>
                {item.turn.topic_id && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      onClick={() => void loadRagInsight(item.turn.topic_id)}
                      disabled={ragLoadingTopicId === item.turn.topic_id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      {ragLoadingTopicId === item.turn.topic_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <BookOpenCheck className="h-3.5 w-3.5" />}
                      解释扣分
                    </button>
                    <button
                      onClick={() => void loadRagInsight(item.turn.topic_id)}
                      disabled={ragLoadingTopicId === item.turn.topic_id}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      <Library className="h-3.5 w-3.5" />
                      用我的知识库补课
                    </button>
                  </div>
                )}
                {renderRagInsight(item.turn.topic_id)}
              </div>
            ))}
          </div>
        )}

        {dynamicTopic && dynamicTurn && (
          <div className="mb-6 rounded-2xl border border-slate-200 bg-white p-6">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-100 text-sm font-medium text-primary-600">
                {dynamicTopic.topic_order}
              </span>
              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-500">
                {dynamicTopic.topic_title}
              </span>
              <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs text-purple-600">
                {dynamicTypeLabel[dynamicTopic.question_type] || dynamicTopic.question_type}
              </span>
              {dynamicTurn.turn_type === 'COACH_RETRY' && (
                <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-600">同题重答</span>
              )}
              {dynamicTurn.turn_type === 'FOLLOW_UP' && (
                <span className="rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-medium text-orange-600">追问</span>
              )}
            </div>
            <h2 className="text-lg font-semibold leading-relaxed text-slate-900">{dynamicTurn.question}</h2>
            {dynamicTopic.evidence_snippet && (
              <p className="mt-4 rounded-xl bg-slate-50 p-3 text-sm leading-6 text-slate-500">
                {dynamicTopic.evidence_snippet}
              </p>
            )}
          </div>
        )}

        {showCoachFeedback && (
          <div className="mb-4 rounded-2xl border border-amber-100 bg-amber-50 p-4">
            <div className="mb-2 flex items-center gap-2 font-medium text-amber-800">
              <Lightbulb className="h-5 w-5" />
              教练提示
            </div>
            {dynamicFeedback && <p className="mb-2 text-sm leading-6 text-amber-800">{dynamicFeedback}</p>}
            {dynamicHint?.message && <p className="text-sm leading-6 text-amber-800">{dynamicHint.message}</p>}
            {dynamicHint?.structure && (
              <div className="mt-3 flex flex-wrap gap-2">
                {dynamicHint.structure.map(item => (
                  <span key={item} className="rounded-md bg-white px-2 py-1 text-xs text-amber-700">{item}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mb-4 flex items-center gap-2 rounded-xl bg-red-50 p-4 text-red-600">
            <AlertCircle className="h-5 w-5 flex-shrink-0" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <textarea
            ref={textareaRef}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="请输入你的回答..."
            rows={6}
            className="w-full resize-none border-0 text-slate-800 placeholder:text-slate-300 focus:outline-none focus:ring-0"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                void handleSubmit();
              }
            }}
          />
          <div className="flex flex-col gap-3 border-t border-slate-100 pt-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={toggleVoiceInput}
                  disabled={submitting || voiceState === 'transcribing'}
                  className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
                    voiceState === 'recording'
                      ? 'bg-red-50 text-red-600 hover:bg-red-100'
                      : voiceState === 'transcribing' || submitting
                        ? 'cursor-not-allowed bg-slate-50 text-slate-300'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                  }`}
                  title="录音后上传到本地语音模型转文字"
                >
                  {voiceState === 'recording' ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  {voiceState === 'recording' ? '停止录音' : voiceState === 'transcribing' ? '转写中...' : '语音输入'}
                </button>
                <span className="text-xs text-slate-400">Ctrl + Enter 提交</span>
                {voiceState === 'recording' && <span className="text-xs font-medium text-primary-600">录音中 {recordingSeconds}s</span>}
              </div>
              {voiceError && <p className="mt-2 text-xs text-orange-600">{voiceError}</p>}
            </div>
            <button
              onClick={handleSubmit}
              disabled={!answer.trim() || submitting || voiceState !== 'idle' || !dynamicTurn}
              className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-medium transition-all ${
                !answer.trim() || submitting || voiceState !== 'idle' || !dynamicTurn
                  ? 'cursor-not-allowed bg-slate-100 text-slate-400'
                  : 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600'
              }`}
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : dynamicTurn?.turn_type === 'COACH_RETRY' ? (
                <>
                  <RotateCcw className="h-4 w-4" />
                  提交重答
                </>
              ) : dynamicTurn?.turn_type === 'FOLLOW_UP' ? (
                <>
                  <Send className="h-4 w-4" />
                  提交追问
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  提交回答
                </>
              )}
            </button>
          </div>
        </div>
        {answeredCount === topicProgress.length && !dynamicReport && (
          <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">所有 topic 已完成，正在整理报告。</div>
        )}
      </div>
    );
  }

  if (completed && report) {
    return (
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-8">
          <CheckCircle2 className="w-16 h-16 text-green-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-slate-900">面试完成！</h1>
          <p className="text-slate-500 mt-2">AI 已完成对你的面试评估</p>
        </div>

        <div className="bg-white rounded-2xl border border-slate-200 p-8 mb-6">
          <div className="flex items-center justify-center mb-6">
            <div className="relative w-36 h-36">
              <svg className="w-36 h-36 -rotate-90" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="50" fill="none" stroke="#e2e8f0" strokeWidth="10" />
                <circle cx="60" cy="60" r="50" fill="none" stroke="#6366f1" strokeWidth="10"
                  strokeDasharray={`${report.overall_score * 3.14} 314`} strokeLinecap="round" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-4xl font-bold text-primary-600">{report.overall_score}</span>
              </div>
            </div>
          </div>

          {report.overall_feedback && (
            <div className="bg-slate-50 rounded-xl p-4 mb-6">
              <p className="text-slate-700 leading-relaxed">{report.overall_feedback}</p>
            </div>
          )}

          {report.strengths.length > 0 && (
            <div className="mb-4">
              <h3 className="font-semibold text-green-700 mb-2">✓ 优势</h3>
              <ul className="space-y-1">
                {report.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-slate-600 pl-4">{s}</li>
                ))}
              </ul>
            </div>
          )}

          {report.improvements.length > 0 && (
            <div>
              <h3 className="font-semibold text-orange-700 mb-2">→ 待改进</h3>
              <ul className="space-y-1">
                {report.improvements.map((s, i) => (
                  <li key={i} className="text-sm text-slate-600 pl-4">{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="space-y-4 mb-8">
          <h2 className="text-lg font-semibold text-slate-900">答题详情</h2>
          {report.question_evaluations.map((q, idx) => {
            const question = report.reference_answers?.find(r => r.question_index === q.question_index);
            const isFollowUp = question?.question?.includes('-追问') || false;
            return (
              <div key={idx} className="bg-white rounded-xl border border-slate-200 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-700">Q{q.question_index + 1}. {q.question}</span>
                    {isFollowUp && (
                      <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">追问</span>
                    )}
                    {q.question_type === 'project' && (
                      <span className="px-1.5 py-0.5 bg-purple-100 text-purple-600 rounded text-xs">项目题</span>
                    )}
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    q.score >= 80 ? 'bg-green-100 text-green-600' :
                    q.score >= 60 ? 'bg-yellow-100 text-yellow-600' :
                    'bg-red-100 text-red-600'
                  }`}>{q.score}分</span>
                </div>
                {q.user_answer && <p className="text-sm text-slate-500 mb-1"><span className="font-medium">你的回答：</span>{q.user_answer}</p>}
                {q.feedback && <p className="text-sm text-slate-500 mb-2"><span className="font-medium">点评：</span>{q.feedback}</p>}

                {/* 知识题：关键得分点 */}
                {q.covered_points && q.covered_points.length > 0 && (
                  <div className="mt-2 p-2 bg-green-50 rounded-lg">
                    <p className="text-xs font-medium text-green-700 mb-1">答到的点：</p>
                    <div className="flex flex-wrap gap-1">
                      {q.covered_points.map((p, i) => (
                        <span key={i} className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs">{p}</span>
                      ))}
                    </div>
                  </div>
                )}
                {q.missed_points && q.missed_points.length > 0 && (
                  <div className="mt-2 p-2 bg-orange-50 rounded-lg">
                    <p className="text-xs font-medium text-orange-700 mb-1">遗漏的点：</p>
                    <div className="flex flex-wrap gap-1">
                      {q.missed_points.map((p, i) => (
                        <span key={i} className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded text-xs">{p}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* 项目题：四维评分 */}
                {q.dimensions && (
                  <div className="mt-2 grid grid-cols-4 gap-2">
                    <div className="text-center p-2 bg-slate-50 rounded-lg">
                      <p className="text-xs text-slate-500">真实性</p>
                      <p className="text-sm font-semibold text-slate-700">{q.dimensions.authenticity}</p>
                    </div>
                    <div className="text-center p-2 bg-slate-50 rounded-lg">
                      <p className="text-xs text-slate-500">技术深度</p>
                      <p className="text-sm font-semibold text-slate-700">{q.dimensions.technical_depth}</p>
                    </div>
                    <div className="text-center p-2 bg-slate-50 rounded-lg">
                      <p className="text-xs text-slate-500">深度</p>
                      <p className="text-sm font-semibold text-slate-700">{q.dimensions.depth}</p>
                    </div>
                    <div className="text-center p-2 bg-slate-50 rounded-lg">
                      <p className="text-xs text-slate-500">表达</p>
                      <p className="text-sm font-semibold text-slate-700">{q.dimensions.expression}</p>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex gap-3">
          <button onClick={() => navigate('/interviews')} className="flex-1 py-3 bg-slate-100 text-slate-700 rounded-xl font-medium hover:bg-slate-200">
            查看所有记录
          </button>
          <button onClick={() => navigate('/interview-hub')} className="flex-1 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25">
            再来一次
          </button>
        </div>
      </div>
    );
  }

  if (completed) {
    const evaluating = session?.evaluate_status ? PROCESSING_STATUSES.has(session.evaluate_status) : true;

    return (
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center">
          {evaluating ? (
            <>
              <Clock3 className="w-16 h-16 text-primary-500 mx-auto mb-4 animate-pulse" />
              <h1 className="text-2xl font-bold text-slate-900 mb-2">面试已完成，报告生成中</h1>
              <p className="text-slate-500">AI 正在整理你的回答并生成评估报告，页面会自动刷新。</p>
            </>
          ) : (
            <>
              <AlertCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
              <h1 className="text-2xl font-bold text-slate-900 mb-2">报告生成失败</h1>
              <p className="text-slate-500">{error || session?.evaluate_error || '请稍后重试或返回列表查看详情。'}</p>
            </>
          )}

          <div className="mt-6 flex gap-3 justify-center">
            <button onClick={() => navigate('/interviews')} className="px-5 py-3 bg-slate-100 text-slate-700 rounded-xl font-medium hover:bg-slate-200">
              返回记录列表
            </button>
            <button onClick={() => navigate(`/interviews/${sessionId}`)} className="px-5 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl font-medium shadow-lg shadow-primary-500/25">
              查看详情页
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/interviews')} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-slate-900">模拟面试</h1>
          <p className="text-sm text-slate-400">
            {session && `第 ${currentQuestion ? currentQuestion.question_index + 1 : '?'} / ${session.total_questions} 题`}
          </p>
        </div>
      </div>

      {session && (
        <div className="mb-6">
          <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary-500 to-primary-400 rounded-full transition-all duration-500"
              style={{ width: `${((currentQuestion?.question_index || 0) / session.total_questions) * 100}%` }}
            />
          </div>
        </div>
      )}

      {questionHistory.length > 0 && (
        <div className="mb-6 space-y-3 max-h-64 overflow-y-auto">
          {questionHistory.map((item, idx) => (
            <div key={idx} className="bg-slate-50 rounded-xl p-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium text-slate-700">Q{item.question.question_index + 1}. {item.question.question}</p>
                {item.question.is_follow_up && (
                  <span className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">追问</span>
                )}
              </div>
              <p className="text-sm text-slate-500 mt-1 line-clamp-2">{item.answer}</p>
            </div>
          ))}
        </div>
      )}

      {currentQuestion && (
        <div className="bg-white rounded-2xl border border-slate-200 p-6 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-7 h-7 bg-primary-100 text-primary-600 rounded-full flex items-center justify-center text-sm font-medium">
              {currentQuestion.question_index + 1}
            </span>
            {currentQuestion.is_follow_up && (
              <span className="px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full text-xs font-medium">追问</span>
            )}
            {currentQuestion.category && (
              <span className="px-2.5 py-0.5 bg-slate-100 text-slate-500 rounded-full text-xs">{currentQuestion.category}</span>
            )}
            {currentQuestion.question_type === 'project' && (
              <span className="px-2.5 py-0.5 bg-purple-100 text-purple-600 rounded-full text-xs">项目题</span>
            )}
          </div>
          <h2 className="text-lg font-semibold text-slate-900 leading-relaxed">{currentQuestion.question}</h2>
        </div>
      )}

      {error && (
        <div className="mb-4 flex items-center gap-2 p-4 bg-red-50 text-red-600 rounded-xl">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="bg-white rounded-2xl border border-slate-200 p-4">
        <textarea
          ref={textareaRef}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="请输入你的回答..."
          rows={6}
          className="w-full resize-none border-0 focus:ring-0 focus:outline-none text-slate-800 placeholder:text-slate-300"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              handleSubmit();
            }
          }}
        />
        <div className="flex flex-col gap-3 pt-3 border-t border-slate-100 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={toggleVoiceInput}
                disabled={submitting || voiceState === 'transcribing'}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  voiceState === 'recording'
                    ? 'bg-red-50 text-red-600 hover:bg-red-100'
                    : voiceState === 'transcribing' || submitting
                      ? 'bg-slate-50 text-slate-300 cursor-not-allowed'
                      : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
                title="录音后上传到本地语音模型转文字"
              >
                {voiceState === 'recording' ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                {voiceState === 'recording' ? '停止录音' : voiceState === 'transcribing' ? '转写中...' : '语音输入'}
              </button>
              <span className="text-xs text-slate-400">Ctrl + Enter 提交</span>
              {voiceState === 'recording' && (
                <span className="text-xs font-medium text-primary-600">录音中 {recordingSeconds}s</span>
              )}
              {voiceState === 'transcribing' && <span className="text-xs font-medium text-primary-600">正在转文字...</span>}
            </div>
            {voiceState === 'idle' && !voiceError && (
              <p className="mt-2 text-xs text-slate-400">点击录音，说完后停止，会自动转成文字并填入回答框。</p>
            )}
            {voiceError && <p className="mt-2 text-xs text-orange-600">{voiceError}</p>}
          </div>
          <button
            onClick={handleSubmit}
            disabled={!answer.trim() || submitting || voiceState !== 'idle'}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-medium text-sm transition-all ${
              !answer.trim() || submitting || voiceState !== 'idle'
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-lg shadow-primary-500/25 hover:from-primary-700 hover:to-primary-600'
            }`}
          >
            {submitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                提交中...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                提交回答
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
