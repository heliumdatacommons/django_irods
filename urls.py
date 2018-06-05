from django.conf.urls import patterns, url

urlpatterns = patterns(
    '',
    # for download request from resource landing page
    url(r'^download/(?P<path>.*)$', 'django_irods.views.download'),
    # for download request from REST API
    url(r'^rest_download/(?P<path>.*)$', 'django_irods.views.rest_download',
        name='rest_download'),
)
