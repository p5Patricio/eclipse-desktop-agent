import logging
from dataclasses import dataclass
from typing import Any
import winrt.windows.ui.notifications.management as mgmt
from eclipse_agent.pal.base import NotificationDaemon
from eclipse_agent.notifications import NotificationCenter, NotificationEvent

logger = logging.getLogger("eclipse.pal.windows.notifications")

@dataclass(frozen=True, kw_only=True)
class WindowsNotificationDaemonResult:
    success: bool
    processed: int
    message: str
    dry_run: bool
    executed: bool = False
    results: tuple[Any, ...] = ()

class WindowsNotificationDaemon(NotificationDaemon):
    def __init__(self, *, center: NotificationCenter | None = None) -> None:
        self.center = center or NotificationCenter()

    def run(
        self,
        *,
        seconds: int | None = 30,
        speak: bool = False,
        dry_run: bool = True,
    ) -> WindowsNotificationDaemonResult:
        if dry_run:
            return WindowsNotificationDaemonResult(
                success=True,
                processed=0,
                message="Prepared Windows notification listener.",
                dry_run=True,
            )
            
        listener = mgmt.UserNotificationListener.current
        access_status = listener.get_access_status()
        
        # 1 corresponds to UserNotificationListenerAccessStatus.ALLOWED
        if access_status != 1:
            logger.warning("Windows notification listener permission denied or unspecified.")
            return WindowsNotificationDaemonResult(
                success=False,
                processed=0,
                message="Windows notification listener permission denied.",
                dry_run=False,
                executed=True,
            )
            
        # Get notifications
        try:
            # 3 corresponds to NotificationKinds.TOAST
            notifications = listener.get_notifications(3)
        except Exception as e:
            return WindowsNotificationDaemonResult(
                success=False,
                processed=0,
                message=f"Failed to query notifications: {e}",
                dry_run=False,
                executed=True,
            )
            
        results = []
        for n in notifications:
            try:
                app_name = "Windows App"
                if hasattr(n, "app_info") and n.app_info:
                    if hasattr(n.app_info, "display_info") and n.app_info.display_info:
                        app_name = n.app_info.display_info.display_name or "Windows App"
                
                summary = ""
                body = ""
                
                binding = None
                if hasattr(n, "notification") and n.notification:
                    if hasattr(n.notification, "visual") and n.notification.visual:
                        toast_generic_id = "ToastGeneric"
                        if hasattr(mgmt, "KnownNotificationBindings") and hasattr(mgmt.KnownNotificationBindings, "toast_generic"):
                            toast_generic_id = mgmt.KnownNotificationBindings.toast_generic
                        binding = n.notification.visual.get_binding(toast_generic_id)
                
                if binding:
                    text_elements = binding.get_text_elements()
                    if text_elements:
                        texts = [t.text for t in text_elements if hasattr(t, "text")]
                        summary = texts[0] if len(texts) > 0 else ""
                        body = " ".join(texts[1:]) if len(texts) > 1 else ""
                
                event = NotificationEvent(
                    app_name=app_name,
                    summary=summary,
                    body=body,
                )
                
                res = self.center.ingest(event, speak=speak, persist=True)
                results.append(res)
            except Exception as e:
                logger.error(f"Error processing notification {getattr(n, 'id', 'unknown')}: {e}")
                
        return WindowsNotificationDaemonResult(
            success=True,
            processed=len(results),
            message=f"Processed {len(results)} notification(s) from Windows notification listener.",
            dry_run=False,
            executed=True,
            results=tuple(results),
        )

