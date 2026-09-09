## Sent to the submitter and PIs when a proposal is accepted or rejected.
<% accepted = project['status'] == 'accepted' %>
<%include file="_projectsHeader.mako"/>

<p style="margin: 0 0 12px;">
  Proposal <b>${project['projectId'] | h}</b> has been
% if accepted:
  <b style="color: #4caf50;">accepted</b>.
% else:
  <b style="color: #f44336;">declined</b>.
% endif
</p>

<p style="margin: 0 0 16px; color: rgba(0, 0, 0, 0.6);">
  ${project['name'] | h}
</p>

% if comment:
<p style="margin: 0 0 16px; padding: 12px; background-color: #fafafa;\
          border-left: 3px solid #e0e0e0;">
  ${comment | h}
</p>
% endif

% if accepted:
<p style="margin: 0 0 16px;">
  A project group and collection have been created for
  ${project['projectId'] | h}; project members can now upload data to it.
</p>
% endif

<p style="margin: 0;">
  <a href="${projectUrl}" target="_blank" style="color: #6200ee;">View proposal</a>
</p>

<%include file="_projectsFooter.mako"/>
