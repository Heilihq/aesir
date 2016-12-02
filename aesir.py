#!/usr/bin/env python3
import os
import sys
import json
import base64
import falcon
import logging
import requests
from wsgiref import simple_server
from docker import Client, errors as docker_error


loglevel = logging.getLevelName('DEBUG')
logformat = logging.Formatter('%(asctime)s - %(name)s - %(threadName)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(logformat)
ch.setLevel(loglevel)
logger = logging.getLogger('AesirAPI')
logger.setLevel(loglevel)
logger.addHandler(ch)

allowed_org = os.getenv('ALLOWED_ORG', False)
docker_api_version = os.getenv('DOCKER_API_VERSION', 'auto')


def _github_auth_is_valid(req, resp, resource, params):
    r = requests.get('https://api.github.com/user/orgs',
                     headers={'Authorization': 'Basic ' + base64.urlsafe_b64encode(req.auth)})
    if r.status_code == 200:
        logger.debug('Working credentials for GitHub')
        for org in r.json():
            if org['login'] == allowed_org:
                params['post_body'] = req.stream.read()
                return True
        logger.error('Not in allowed organization')
        raise falcon.HTTPForbidden('User not allowed to deploy', 'User is not in allowed organization to deploy')
    logger.error('Got wrong GitHub credentials')
    logger.debug('Response from GitHub HTTP {}:\n{}'.format(r.status_code, r.json()))
    return False


@falcon.before(_github_auth_is_valid)
class BuildResource(object):
    def on_post(self, req, resp, post_body):
        try:
            post_body = json.loads(post_body)
        except ValueError:
            logger.error('No POST body')
            raise falcon.HTTPBadRequest('Missing parameters', 'Missing build request body or bad request')
        if not post_body.get('git_repo') or not post_body.get('docker_image'):
            logger.error('Missing "git_repo" or "docker_image"')
            raise falcon.HTTPMissingParam('Missing git_repo({}) or docker_image({})'.
                                          format(post_body.get('git_repo'), post_body.get('docker_image')))
        logger.debug('Building image')
        docker_build = build_image(req.auth, post_body['docker_image'], post_body['git_repo'],
                                   post_body.get('docker_tag'), post_body.get('git_branch'),
                                   post_body.get('git_directory'))
        if docker_build:
            logger.error('Build failed')
            raise falcon.HTTPInternalServerError('Docker Build failed', docker_build)

        if 'push' in req.query_string:
            logger.debug('Push the image to repo')
            docker_push = push_image(post_body['docker_image'], post_body.get('docker_tag'),
                                     post_body.get('registry_user'), post_body.get('registry_password'))
            if docker_push:
                logger.error('Push failed')
                raise falcon.HTTPInternalServerError('Docker Push failed', docker_push)
        resp.status = falcon.HTTP_200  # This is the default status
        resp.body = '{{"title": "Build Successful", "description": "Successfully build and pushed {} image and it\'s ' \
                    'ready to be deployed"}}'.format(post_body['docker_image'])


def build_image(git_auth, image_name, git_repo, image_tag='latest', git_branch=None, git_directory=None):
    cli = Client(base_url='unix://var/run/docker.sock', version=docker_api_version)

    if not git_repo.endswith('.git'):
        logger.debug('Adding .git to {}'.format(git_repo))
        git_repo += '.git'
    git_repo = 'https://' + git_auth + '@' + git_repo[8:]
    if git_directory:
        logger.debug('Adding : to {}'.format(git_directory))
        git_directory = ':' + git_directory
        if git_branch is None:
            logger.debug('Adding # to {}'.format(git_branch))
            git_branch = '#'
        else:
            logger.debug('Adding # to {}'.format(git_branch))
            git_branch = '#' + git_branch
    else:
        git_directory = ''
    if not git_branch.startswith('#'):
        logger.debug('Adding # to {}'.format(git_branch))
        git_branch = '#' + git_branch

    logger.debug(git_repo + git_branch + git_directory)
    logger.debug(image_name + ':' + image_tag)

    try:
        response = [line for line in cli.build(git_repo + git_branch + git_directory,
                                               rm=True,
                                               tag=image_name + ':' + image_tag)]
    except docker_error as msg:
        logger.error('Something went wrong:\n{}'.format(msg))
        return msg
    else:
        logger.debug(response)
        return None


def push_image(image_name, image_tag='latest', registry_user=False, registry_pass=False):
    cli = Client(base_url='unix://var/run/docker.sock', version=docker_api_version)

    try:
        if registry_user and registry_pass:
            registry_url = image_name.split('/')[0]
            response = [line for line in cli.login(registry_user, registry_pass, registry_url)]
        response = [line for line in cli.push(image_name + ':' + image_tag, stream=True)]
    except docker_error as msg:
        logger.error('Failed to push image:\n{}'.format(msg))
        return msg
    else:
        logger.debug(response)
        return None

app = falcon.API()
app.add_route('/build', BuildResource())

logger.info('Starting Aesir API')
httpd = simple_server.make_server('', 8000, app)
httpd.serve_forever()
