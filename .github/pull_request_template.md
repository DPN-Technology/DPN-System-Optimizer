## DPN change summary

<!-- What changed and why? -->

## Safety assessment

- [ ] Cleanup is still preview-first; `--apply` is the only CLI deletion authorization
- [ ] No user documents, browser secrets, registry cleaners, or arbitrary path deletion
- [ ] Symlink/junction checks and old-file guards remain intact
- [ ] Startup and system integrity actions remain read-only without explicit approval
- [ ] Added or updated regression tests for any behavior changes

## Verification

- [ ] DPN Green Gates — Required policy gate passed
- [ ] DPN CodeQL Security passed
- [ ] DPN Dependency Review passed (where applicable)
- [ ] Windows app or packaging was tested where impacted

## Rollback

<!-- State how to revert safely and whether cleanup has irreversible effects. -->
