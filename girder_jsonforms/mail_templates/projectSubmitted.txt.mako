## Plain-text alternative for projectSubmitted.mako. Every message carries
## both: an HTML-only body reads as opaque to spam filters, and some readers
## see only this one. Keep the wording in step with the HTML version.
Proposal ${project['projectId']} is ready for review.

${project['name']}
% if submitter:
Submitted by ${submitter}
% endif

Review the proposal:
${projectUrl}
<%include file="_projectsFooter.txt.mako"/>\
