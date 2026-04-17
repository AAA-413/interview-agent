import io
import logging
from datetime import datetime

from app.modules.resume.schemas import ResumeDetailDTO

logger = logging.getLogger(__name__)


class PdfExportService:
    async def export_resume_analysis_pdf(self, detail: ResumeDetailDTO) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import mm
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            from reportlab.lib import colors

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            elements = []

            title_style = ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=18, spaceAfter=20)
            elements.append(Paragraph("简历分析报告", title_style))
            elements.append(Spacer(1, 10))

            info_style = ParagraphStyle("Info", parent=styles["Normal"], fontSize=10)
            elements.append(Paragraph(f"文件名: {detail.filename}", info_style))
            elements.append(Paragraph(f"上传时间: {detail.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')}", info_style))
            elements.append(Paragraph(f"分析状态: {detail.analyze_status.value}", info_style))
            elements.append(Spacer(1, 15))

            if detail.analyses:
                analysis = detail.analyses[0]

                heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=14)
                elements.append(Paragraph("评分概览", heading_style))
                elements.append(Spacer(1, 8))

                score_data = [
                    ["维度", "得分", "满分"],
                    ["项目经验", str(analysis.project_score or 0), "40"],
                    ["技能匹配", str(analysis.skill_match_score or 0), "20"],
                    ["内容完整性", str(analysis.content_score or 0), "15"],
                    ["结构清晰度", str(analysis.structure_score or 0), "15"],
                    ["表达专业性", str(analysis.expression_score or 0), "10"],
                    ["总分", str(analysis.overall_score or 0), "100"],
                ]
                table = Table(score_data, colWidths=[120, 80, 80])
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, 0), 12),
                            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                            ("BACKGROUND", (0, -1), (-1, -1), colors.beige),
                            ("GRID", (0, 0), (-1, -1), 1, colors.black),
                        ]
                    )
                )
                elements.append(table)
                elements.append(Spacer(1, 15))

                if analysis.summary:
                    elements.append(Paragraph("简历摘要", heading_style))
                    elements.append(Paragraph(analysis.summary, info_style))
                    elements.append(Spacer(1, 10))

                if analysis.strengths:
                    elements.append(Paragraph("优势点", heading_style))
                    for s in analysis.strengths:
                        elements.append(Paragraph(f"• {s}", info_style))
                    elements.append(Spacer(1, 10))

                if analysis.suggestions:
                    elements.append(Paragraph("改进建议", heading_style))
                    for sug in analysis.suggestions:
                        elements.append(
                            Paragraph(
                                f"[{sug.priority}] {sug.category} - {sug.issue}: {sug.recommendation}",
                                info_style,
                            )
                        )
            else:
                elements.append(Paragraph("暂无分析结果", info_style))

            doc.build(elements)
            return buffer.getvalue()

        except ImportError:
            logger.error("未安装 reportlab 库，无法导出 PDF")
            raise
        except Exception as e:
            logger.error("PDF 导出失败: %s", str(e))
            raise


    async def export_interview_pdf(self, detail) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            from reportlab.lib import colors

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4)
            styles = getSampleStyleSheet()
            elements = []

            title_style = ParagraphStyle("CustomTitle", parent=styles["Title"], fontSize=18, spaceAfter=20)
            heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=14)
            info_style = ParagraphStyle("Info", parent=styles["Normal"], fontSize=10)
            bold_style = ParagraphStyle("Bold", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold")

            elements.append(Paragraph("面试评估报告", title_style))
            elements.append(Spacer(1, 10))

            elements.append(Paragraph(f"会话ID: {detail.session_id}", info_style))
            elements.append(Paragraph(f"面试方向: {detail.skill_id or 'N/A'}", info_style))
            elements.append(Paragraph(f"难度: {detail.difficulty or 'N/A'}", info_style))
            elements.append(Paragraph(f"总题数: {detail.total_questions or 0}", info_style))
            elements.append(Paragraph(f"综合得分: {detail.overall_score or 0}/100", info_style))
            if detail.created_at:
                elements.append(Paragraph(f"创建时间: {detail.created_at.strftime('%Y-%m-%d %H:%M:%S')}", info_style))
            if detail.completed_at:
                elements.append(Paragraph(f"完成时间: {detail.completed_at.strftime('%Y-%m-%d %H:%M:%S')}", info_style))
            elements.append(Spacer(1, 15))

            if detail.overall_feedback:
                elements.append(Paragraph("综合评价", heading_style))
                elements.append(Paragraph(detail.overall_feedback, info_style))
                elements.append(Spacer(1, 10))

            if detail.strengths:
                elements.append(Paragraph("优势", heading_style))
                for s in detail.strengths:
                    elements.append(Paragraph(f"• {s}", info_style))
                elements.append(Spacer(1, 10))

            if detail.improvements:
                elements.append(Paragraph("待改进", heading_style))
                for imp in detail.improvements:
                    elements.append(Paragraph(f"• {imp}", info_style))
                elements.append(Spacer(1, 10))

            if detail.question_evaluations:
                elements.append(Paragraph("逐题评估", heading_style))
                elements.append(Spacer(1, 8))

                for qe in detail.question_evaluations:
                    elements.append(Paragraph(f"问题 {qe.get('question_index', 0) + 1}: {qe.get('question', '')}", bold_style))
                    if qe.get('category'):
                        elements.append(Paragraph(f"分类: {qe['category']}", info_style))
                    if qe.get('user_answer'):
                        elements.append(Paragraph(f"回答: {qe['user_answer'][:200]}", info_style))
                    elements.append(Paragraph(f"得分: {qe.get('score', 0)}/100", info_style))
                    if qe.get('feedback'):
                        elements.append(Paragraph(f"反馈: {qe['feedback']}", info_style))
                    elements.append(Spacer(1, 8))

            doc.build(elements)
            return buffer.getvalue()

        except ImportError:
            logger.error("未安装 reportlab 库，无法导出 PDF")
            raise
        except Exception as e:
            logger.error("面试报告 PDF 导出失败: %s", str(e))
            raise


pdf_export_service = PdfExportService()
