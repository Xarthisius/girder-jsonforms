## Plain-text alternative for projectDecision.mako; see the note there.
<% accepted = project['status'] == 'accepted' %>\
Proposal ${project['projectId']} has been ${'accepted' if accepted else 'declined'}.

${project['name']}
% if comment:

${comment}
% endif
% if accepted:

A project group and collection have been created for ${project['projectId']};
project members can now upload data to it.
% endif

View the proposal:
${projectUrl}
<%include file="_projectsFooter.txt.mako"/>\
