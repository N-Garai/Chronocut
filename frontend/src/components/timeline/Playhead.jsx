/** Playhead — vertical line at playheadMs, previewed at previewMs during a seek. */
export default function Playhead({ playheadMs, previewMs, pps }) {
  const ms = previewMs != null ? previewMs : playheadMs
  const show = ms != null
  return (
    <>
      {previewMs != null && previewMs !== playheadMs && (
        <div
          aria-hidden
          className="absolute top-0 bottom-0 z-20 w-px bg-amberglow/40"
          style={{ left: Math.round((previewMs / 1000) * pps) }}
        />
      )}
      <div
        data-testid="playhead"
        className={`absolute top-0 bottom-0 z-20 w-0.5 ${show ? 'bg-amberglow' : 'opacity-0'} pointer-events-none`}
        style={{ left: Math.round(((ms || 0) / 1000) * pps) - 1 }}
      >
        <span className="absolute -left-[5px] -top-[1px] h-2.5 w-2.5 rotate-45 rounded-[2px] bg-amberglow" />
      </div>
    </>
  )
}
