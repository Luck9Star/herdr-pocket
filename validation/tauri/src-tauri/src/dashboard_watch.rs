//! UI review cache only. The transport rechecks typed intent against its own
//! authoritative snapshot; this cache cannot turn event payloads into targets.
use herdr_readonly_transport::{
    DashboardTarget, Pane,
    session_watch::{SessionWatchPhase, SessionWatchUpdate},
};
#[derive(Default)]
pub struct DashboardReview {
    epoch: u64,
    revision: u64,
    selectable: bool,
    panes: Vec<Pane>,
}
impl DashboardReview {
    pub fn update(&mut self, current_epoch: u64, update: &SessionWatchUpdate) -> bool {
        if update.epoch == 0
            || update.epoch > 9_007_199_254_740_991
            || (update.phase == SessionWatchPhase::Fresh && update.panes.is_none())
            || (matches!(
                update.phase,
                SessionWatchPhase::Stale | SessionWatchPhase::Refreshing
            ) && update.panes.is_some())
            || update.epoch != current_epoch
            || update.epoch < self.epoch
            || update.revision == 0
            || update.revision > 9_007_199_254_740_991
            || (update.epoch == self.epoch && update.revision <= self.revision)
        {
            return false;
        }
        self.epoch = update.epoch;
        self.revision = update.revision;
        self.selectable = update.phase == SessionWatchPhase::Fresh
            || (update.phase == SessionWatchPhase::Unavailable && update.panes.is_some());
        if let Some(panes) = &update.panes {
            self.panes = panes.clone();
        }
        true
    }
    pub fn select(
        &self,
        epoch: u64,
        revision: u64,
        pane: String,
        terminal: String,
    ) -> Result<DashboardTarget, &'static str> {
        if !self.selectable || epoch != self.epoch || revision != self.revision {
            return Err("dashboard_stale");
        }
        if !self
            .panes
            .iter()
            .any(|p| p.pane_id == pane && p.terminal_id == terminal)
        {
            return Err("target_changed");
        }
        Ok(DashboardTarget {
            pane_id: pane,
            terminal_id: terminal,
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn update(
        epoch: u64,
        revision: u64,
        phase: SessionWatchPhase,
        terminal: &str,
    ) -> SessionWatchUpdate {
        SessionWatchUpdate {
            epoch,
            revision,
            phase,
            reason: "fixture",
            panes: if phase == SessionWatchPhase::Fresh || phase == SessionWatchPhase::Unavailable {
                Some(vec![Pane {
                    pane_id: "w1:p1".into(),
                    terminal_id: terminal.into(),
                    label: None,
                    agent: None,
                    agent_status: "unknown",
                    workspace: None,
                    tab: None,
                }])
            } else {
                None
            },
        }
    }
    #[test]
    fn revision_epoch_and_exact_reviewed_terminal_are_required() {
        let mut r = DashboardReview::default();
        assert!(r.update(1, &update(1, 1, SessionWatchPhase::Fresh, "term_abc")));
        assert!(r.select(1, 1, "w1:p1".into(), "term_abc".into()).is_ok());
        assert!(!r.update(1, &update(1, 1, SessionWatchPhase::Fresh, "term_def")));
        assert!(r.update(1, &update(1, 2, SessionWatchPhase::Fresh, "term_def")));
        assert!(r.select(1, 1, "w1:p1".into(), "term_abc".into()).is_err());
        assert!(r.select(1, 2, "w1:p1".into(), "term_abc".into()).is_err());
        assert!(!r.update(2, &update(1, 3, SessionWatchPhase::Fresh, "term_abc")));
        assert!(r.update(2, &update(2, 1, SessionWatchPhase::Refreshing, "term_def")));
        assert!(r.select(2, 1, "w1:p1".into(), "term_def".into()).is_err());
    }
    #[test]
    fn unsupported_snapshot_is_explicit_and_stale_retains_no_selection_authority() {
        let mut r = DashboardReview::default();
        assert!(r.update(1, &update(1, 1, SessionWatchPhase::Unavailable, "term_abc")));
        assert!(r.select(1, 1, "w1:p1".into(), "term_abc".into()).is_ok());
        assert!(r.update(1, &update(1, 2, SessionWatchPhase::Stale, "term_abc")));
        assert!(r.select(1, 2, "w1:p1".into(), "term_abc".into()).is_err());
    }
}
