# Create your views here.
from uuid import uuid4
import os
import mimetypes

from rest_framework.decorators import api_view

from django_irods import icommands
from django_irods.storage import IrodsStorage
from django.conf import settings
from django.http import HttpResponse, FileResponse

from hs_core.views.utils import authorize, ACTION_TO_AUTHORIZE
from hs_core.hydroshare.hs_bagit import create_bag_by_irods
from hs_core.hydroshare.resource import FILE_SIZE_LIMIT
from hs_core.signals import pre_download_file
from hs_core.hydroshare import check_resource_type

from . import models as m
from .icommands import Session, GLOBAL_SESSION


@api_view(['GET'])
def download(request, path, *args, **kwargs):
    idx = -1
    federated_path = ''
    if settings.HS_LOCAL_PROXY_USER_IN_FED_ZONE:
        idx = path.find(settings.HS_LOCAL_PROXY_USER_IN_FED_ZONE)
    if idx > 0:
        # the resource is stored in federated zone
        istorage = IrodsStorage('federated')
        session = icommands.ACTIVE_SESSION
        s_idx = idx + len(settings.HS_LOCAL_PROXY_USER_IN_FED_ZONE)+1
        rel_path = path[s_idx:]
        split_path_strs = rel_path.split('/')
        # prepend / as needed so that path for federated zone is absolute path
        if not path.startswith('/'):
            path = '/{}'.format(path)
        federated_path = path[:s_idx]
    else:
        istorage = IrodsStorage()
        split_path_strs = path.split('/')
        if 'environment' in kwargs:
            environment = int(kwargs['environment'])
            environment = m.RodsEnvironment.objects.get(pk=environment)
            session = Session("/tmp/django_irods", settings.IRODS_ICOMMANDS_PATH, session_id=uuid4())
            session.create_environment(environment)
            session.run('iinit', None, environment.auth)
        elif getattr(settings, 'IRODS_GLOBAL_SESSION', False):
            session = GLOBAL_SESSION
        elif icommands.ACTIVE_SESSION:
            session = icommands.ACTIVE_SESSION
        else:
            raise KeyError('settings must have IRODS_GLOBAL_SESSION set if there is no environment object')

    if split_path_strs[0] == 'bags':
        res_id = os.path.splitext(split_path_strs[1])[0]
    else:
        res_id = split_path_strs[0]
    res, authorized, _ = authorize(request, res_id, needed_permission=ACTION_TO_AUTHORIZE.VIEW_RESOURCE,
                                   raises_exception=False)
    if not authorized:
        response = HttpResponse()
        response.content = "<h1>You do not have permission to download this resource!</h1>"
        return response

    # send signal for pre download file
    resource_cls = check_resource_type(res.resource_type)
    download_file_name = split_path_strs[-1]
    pre_download_file.send(sender=resource_cls, resource=res, download_file_name=download_file_name)

    # do on-demand bag creation
    bag_modified = "false"
    # needs to check whether res_id collection exists before getting/setting AVU on it to accommodate the case
    # where the very same resource gets deleted by another request when it is getting downloaded
    if federated_path:
        if federated_path.endswith('/'):
            res_root = '{}{}'.format(federated_path, res_id)
        else:
            res_root = '{}/{}'.format(federated_path, res_id)
    else:
        res_root = res_id
    if istorage.exists(res_root):
        bag_modified = istorage.getAVU(res_root, 'bag_modified')
    if bag_modified == "true":
        ret_status = create_bag_by_irods(res_id, istorage)
        # only reset bag_modified to true when create_bag_by_irods succeeds.
        # At this point the irods exception is not populated to the web front end
        # as a workaround since race condition is not handled on iRODS side for
        # bag creation and we don't want to show race condition-related iRODs exceptions
        # when bag download can still proceed successfully.
        if istorage.exists(res_root) and ret_status:
            istorage.setAVU(res_root, 'bag_modified', "false")

    # obtain mime_type to set content_type
    mtype = 'application-x/octet-stream'
    mime_type = mimetypes.guess_type(path)
    if mime_type[0] is not None:
        mtype = mime_type[0]

    # retrieve file size to set up Content-Length header
    stdout = session.run("ils", None, "-l", path)[0].split()
    flen = int(stdout[3])
    if flen <= FILE_SIZE_LIMIT:
        options = ('-',) # we're redirecting to stdout.
        proc = session.run_safe('iget', None, path, *options)
        response = FileResponse(proc.stdout, content_type=mtype)
        response['Content-Disposition'] = 'attachment; filename="{name}"'.format(name=path.split('/')[-1])
        response['Content-Length'] = flen
        return response
    else:
        response = HttpResponse()
        response.content = "<h1>File larger than 1GB cannot be downloaded directly via HTTP." \
                           "Please download the large file via iRODS clients.</h1>"
        return response


def list(request, *args, **kwargs):
    if 'environment' in kwargs:
        environment = int(kwargs['environment'])
        environment = m.RodsEnvironment.objects.get(pk=environment)
        session = Session("/tmp/django_irods", settings.IRODS_ICOMMANDS_PATH, session_id=uuid4())
        session.create_environment(environment)
        session.run('iinit', None, environment.auth)
    elif getattr(settings, 'IRODS_GLOBAL_SESSION', False):
        session = GLOBAL_SESSION
    else:
        raise KeyError('settings must have IRODS_GLOBAL_SESSION set if there is no environment object')

    options = ('-',) # we're redirecting to stdout.

    proc = session.run_safe('ils', None, *options)
    response = HttpResponse(proc.stdout)
    return response
