import { interviewSheetApi, type InterviewSheet } from '../api/interviewSheet';
import type { Project } from '../api/types';

/** Reuse the existing project-filtered endpoint, with bounded request concurrency. */
export async function loadProjectInterviewSheets(projects: readonly Project[]): Promise<InterviewSheet[]> {
  const sheets: InterviewSheet[] = [];
  for (let offset = 0; offset < projects.length; offset += 4) {
    const responses = await Promise.all(
      projects.slice(offset, offset + 4).map((project) => interviewSheetApi.listAll({ job_id: project.id }))
    );
    sheets.push(...responses.flatMap((response) => response.sheets));
  }
  const projectIds = new Set(projects.map((project) => project.id));
  return [...new Map(sheets.filter((sheet) => projectIds.has(sheet.job_id)).map((sheet) => [sheet.id, sheet])).values()];
}
