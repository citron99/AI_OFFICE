import React, {useEffect, useRef} from "react";

export default function DecisionDialog({title, busy, onClose, children}) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    const trigger = document.activeElement;
    dialog.showModal();
    return () => {
      dialog.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return <dialog ref={ref} className="modal" aria-labelledby="decision-title"
    onCancel={event => {event.preventDefault(); if (!busy) onClose();}}>
    <span className="eyebrow">РЕШЕНИЕ СОБСТВЕННИКА</span>
    <h2 id="decision-title">{title}</h2>
    {children}
  </dialog>;
}
