## Branded header for the projects (proposal) workflow emails.
##
## Mirrors the proposals UI app bar (aimdl-projects src/components/AppBar.vue):
## a muted surface strip under a primary-colored rule, with the brand as the
## title. Colors are the design tokens from that app's src/assets/base.css
## (--c-primary #6200ee, --c-surface-muted #f5f5f5, --c-border #e0e0e0),
## inlined because email clients drop <style> blocks and custom properties.
##
## The logo is opt-in (``logoUrl``, sized by ``logoHeight``, default 32px), so
## the header is typographic unless jsonforms.mail_logo names a file. At send
## time ``logoUrl`` is a "cid:" reference to the attached image (lib/mail.py),
## never a remote URL -- rendering the message must not make the reader's
## client fetch anything from us. It also accepts an https or data: URI, which
## is what scripts/preview_mail.py --logo-file uses to stand in for the
## attachment locally.
##
## Opens the page container; _projectsFooter.mako closes it. Always pair them.
## Named _projects* rather than _header/_footer so it cannot shadow the
## same-named partials in girder/mail_templates, which every core email uses.
<div style="max-width: 600px; margin: 0; padding: 0;\
            font-family: Roboto, Helvetica, Arial, sans-serif;\
            font-size: 14px; line-height: 1.5; color: rgba(0, 0, 0, 0.87);">
  <div style="height: 4px; background-color: #6200ee;"></div>
  <div style="background-color: #f5f5f5; border-bottom: 1px solid #e0e0e0;\
              padding: 14px 16px; font-size: 18px; font-weight: 500;">
% if logoUrl:
<% _logo_h = logoHeight if logoHeight else 32 %>\
    <img src="${logoUrl}" alt="" height="${_logo_h}"\
         style="height: ${_logo_h}px; width: auto;\
         vertical-align: middle; margin-right: 12px;" />
% endif
    <span style="vertical-align: middle;">${brandName | h}</span>
  </div>
  <div style="padding: 16px;">
