export function archivePresentation(file: any, now = Date.now() / 1000) {
  const detail = file?.archive_detail || {};
  const when = (timestamp: number) => new Date(timestamp * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  let [cloud, color] = ({ success: ['有上传成功记录', 'blue'], archived: ['以完整文件归档', 'gray'], failed: ['上传失败', 'red'], paused: ['上传已暂停', 'gray'], cancelled: ['上传已取消', 'gray'], uploading: ['上传中', 'blue'], pending: ['等待上传', 'blue'] } as Record<string, string[]>)[file?.upload_status] || ['未加入上传', 'gray'];
  if (detail.cleanup_error) { cloud = '复核或清理需处理'; color = 'orange'; }
  else if (detail.remote_checked_at) { cloud = `${detail.merged_path ? '完整文件' : '文件'}已复核 · ${when(detail.remote_checked_at)}`; color = 'green'; }
  else if (file?.upload_status === 'success' && detail.upload_evidence !== 'task') { cloud = '曾上传，待复核'; color = 'orange'; }
  const local = detail.cleanup_error ? '已保留，等待处理' : detail.upload_evidence === 'history' && !detail.remote_checked_at ? '已保留，等待归档复核' : detail.cleanup_enabled === false ? '已保留，尚未满足自动清理条件' : detail.cleanup_due_at ? detail.cleanup_due_at > now ? `保留至 ${when(detail.cleanup_due_at)}` : '已到清理时间，等待处理' : '已保存在本机';
  return { cloud, color, local };
}
