## Sent to reviewers when a proposal moves from 'draft' to 'under review'.
<%include file="_projectsHeader.mako"/>

<p style="margin: 0 0 12px;">
  Proposal <b>${project['projectId'] | h}</b> is ready for review.
</p>

<p style="margin: 0 0 16px; color: rgba(0, 0, 0, 0.6);">
  ${project['name'] | h}<br/>
% if submitter:
  Submitted by ${submitter | h}
% endif
</p>

<p style="margin: 0;">
  <a href="${projectUrl}" target="_blank"
     style="background-color: #6200ee; color: #ffffff; text-decoration: none;\
            padding: 10px 16px; border-radius: 4px; display: inline-block;">
    Review proposal
  </a>
</p>

<%include file="_projectsFooter.mako"/>
