# Krita Work Timer Plugin
# A sophisticated work time tracker with cognitive work detection

from krita import Krita, DockWidgetFactory, DockWidgetFactoryBase
from .work_timer_docker import WorkTimerDocker
from .work_timer_extension import WorkTimerExtension

DOCKER_ID = "krita_work_timer_docker"

# Get Krita instance
instance = Krita.instance()

# Register the extension (runs when plugin is enabled, tracks time)
instance.addExtension(WorkTimerExtension(instance))

# Register the dock widget factory (UI display)
dock_widget_factory = DockWidgetFactory(
    DOCKER_ID,
    DockWidgetFactoryBase.DockRight,
    WorkTimerDocker
)
instance.addDockWidgetFactory(dock_widget_factory)
